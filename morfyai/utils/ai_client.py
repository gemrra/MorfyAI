# -*- coding: utf-8 -*-
"""
MorfyAI - AI Client
OpenAI-compatible API client with Function Calling, streaming, and web search.
"""

import os
import sys
import json
import ssl
import time
import re
from typing import List, Dict, Optional, Any, Callable, Generator, Tuple
from urllib.parse import quote_plus

from shared.common_utils import load_config, save_config

# Force-use dependencies from the local lib directory
_lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'lib')
if os.path.exists(_lib_path):
    # Prepend lib to sys.path so it takes priority
    if _lib_path in sys.path:
        sys.path.remove(_lib_path)
    sys.path.insert(0, _lib_path)

# Import requests
HAS_REQUESTS = False
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    pass

# Route diagnostic prints to in-app Debug Console (silences Houdini Console popup)
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

try:
    from morfyai.utils.reasoning_capabilities import get_reasoning_capability, BUDGET_TOKENS_BY_LEVEL
except Exception:
    def get_reasoning_capability(model, provider=""):
        return {"kind": "none", "options": []}
    BUDGET_TOKENS_BY_LEVEL = {"low": 2000, "medium": 6000, "high": 10000}


# ============================================================
# Web search
# ============================================================

class WebSearcher:
    """Web search utility - multi-engine auto-fallback (Brave -> DuckDuckGo) + cache"""

    # Brave Search (free HTML scraping, Svelte SSR, good result quality)
    BRAVE_URL = "https://search.brave.com/search"

    # DuckDuckGo HTML search (no API key required, fallback)
    DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"

    # Shared request headers
    _HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
    }

    # Search result cache: key -> (timestamp, result)
    _search_cache: Dict[str, tuple] = {}
    _CACHE_TTL = 300  # 5 minutes

    # Page body cache: url -> (timestamp, text_lines)
    _page_cache: Dict[str, tuple] = {}
    _PAGE_CACHE_TTL = 600  # 10 minutes

    # Trafilatura availability
    _HAS_TRAFILATURA = False

    def __init__(self):
        # Detect trafilatura availability (only once)
        if not WebSearcher._HAS_TRAFILATURA:
            try:
                import trafilatura  # noqa: F401
                WebSearcher._HAS_TRAFILATURA = True
            except ImportError:
                pass
    # ------------------------------------------------------------------
    # Encoding fix: requests defaults to ISO-8859-1 which causes mojibake
    # ------------------------------------------------------------------

    @staticmethod
    def _fix_encoding(response) -> str:
        """Detect and fix HTTP response encoding to avoid mojibake.

        Priority:
        1. Charset explicitly declared in Content-Type header (excludes ISO-8859-1 default)
        2. HTML <meta charset="..."> tag
        3. requests.apparent_encoding (based on chardet / charset_normalizer)
        4. Fall back to UTF-8
        """
        # 1) Charset from Content-Type
        ct_enc = response.encoding
        if ct_enc and ct_enc.lower() not in ('iso-8859-1', 'latin-1', 'ascii'):
            return response.text

        # 2) HTML meta tag
        raw = response.content[:8192]
        meta_match = re.search(
            rb'<meta[^>]*charset=["\']?\s*([a-zA-Z0-9_-]+)',
            raw, re.IGNORECASE,
        )
        if meta_match:
            declared = meta_match.group(1).decode('ascii', errors='ignore').strip()
            try:
                response.encoding = declared
                return response.text
            except (LookupError, UnicodeDecodeError):
                pass

        # 3) apparent_encoding (chardet)
        apparent = getattr(response, 'apparent_encoding', None)
        if apparent:
            try:
                response.encoding = apparent
                return response.text
            except (LookupError, UnicodeDecodeError):
                pass

        # 4) Fall back to UTF-8
        response.encoding = 'utf-8'
        return response.text

    @staticmethod
    def _decode_entities(text: str) -> str:
        """Decode HTML entities: &amp; &lt; &gt; &quot; &#xxxx; etc."""
        import html as _html
        try:
            return _html.unescape(text)
        except Exception:
            return text

    # ------------------------------------------------------------------
    # Search (with cache + 3-tier fallback)
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> Dict[str, Any]:
        """Run a web search (cache + multi-engine auto-fallback).

        Priority: cache -> Brave scrape -> DuckDuckGo scrape.
        First engine that succeeds with results wins; otherwise try the next.
        """
        # --- Cache lookup ---
        cache_key = f"{query}|{max_results}"
        cached = self._search_cache.get(cache_key)
        if cached:
            ts, cached_result = cached
            if (time.time() - ts) < self._CACHE_TTL:
                cached_result = dict(cached_result)
                cached_result['source'] = cached_result.get('source', '') + '(cached)'
                return cached_result

        errors = []

        # 1. Brave Search (free HTML scrape, good quality)
        result = self._search_brave(query, max_results, timeout)
        if result.get('success') and result.get('results'):
            self._search_cache[cache_key] = (time.time(), result)
            return result
        errors.append(f"Brave: {result.get('error', 'no results')}")

        # 2. DuckDuckGo (fallback)
        result = self._search_duckduckgo(query, max_results, timeout)
        if result.get('success') and result.get('results'):
            self._search_cache[cache_key] = (time.time(), result)
            return result
        errors.append(f"DDG: {result.get('error', 'no results')}")
        
        return {"success": False, "error": f"All engines failed: {'; '.join(errors)}", "results": []}

    # ---------- Brave Search ----------

    def _search_brave(self, query: str, max_results: int, timeout: int) -> Dict[str, Any]:
        """Search via Brave (HTML scrape, no API key required, good quality)."""
        if not HAS_REQUESTS:
            return {"success": False, "error": "requests not installed", "results": []}
        try:
            params = {'q': query, 'source': 'web'}
            response = requests.get(
                self.BRAVE_URL, params=params, headers=self._HEADERS, timeout=timeout,
            )
            response.raise_for_status()
            page_html = self._fix_encoding(response)
            results = self._parse_brave_html(page_html, max_results)
            if results:
                return {"success": True, "query": query, "results": results, "source": "Brave"}
            return {"success": False, "error": "Brave returned page but no results parsed", "results": []}
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}

    def _parse_brave_html(self, page_html: str, max_results: int) -> List[Dict[str, str]]:
        """Parse a Brave Search results page (Svelte SSR structure).

        Brave structure:
          <div class="snippet svelte-..." data-type="web" data-pos="N">
            <a href="URL">
              <div class="title search-snippet-title ...">TITLE</div>
            </a>
            <div class="snippet-description ...">DESCRIPTION</div>
            or text paragraph inlined directly
          </div>
        """
        results: List[Dict[str, str]] = []
        
        block_starts = list(re.finditer(
            r'<div[^>]*class="snippet\b[^"]*"[^>]*data-type="web"[^>]*>',
            page_html, re.IGNORECASE,
        ))
        
        for i, match in enumerate(block_starts[:max_results + 5]):
            start = match.start()
            end = block_starts[i + 1].start() if i + 1 < len(block_starts) else start + 4000
            block = page_html[start:end]
            
            # URL: first external <a href="https://...">
            url_m = re.search(r'<a[^>]*href="(https?://[^"]+)"', block, re.IGNORECASE)
            url = url_m.group(1) if url_m else ''
            if not url or 'brave.com' in url:
                continue
            
            # Title: class="title search-snippet-title ..."
            title = ''
            for title_pat in (
                r'class="title\b[^"]*search-snippet-title[^"]*"[^>]*>(.*?)</div>',
                r'class="[^"]*search-snippet-title[^"]*"[^>]*>(.*?)</(?:span|div)>',
                r'class="snippet-title[^"]*"[^>]*>(.*?)</(?:span|div)>',
            ):
                title_m = re.search(title_pat, block, re.DOTALL | re.IGNORECASE)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    # Drop Chinese-format date suffix (e.g. "Title 2025-YY-11-MM-6-DD -").
                    # Year/Month/Day Han glyphs use \\u escapes so the source file stays Chinese-free.
                    title = re.sub('\\s*\\d{4}\\u5e74\\d{1,2}\\u6708\\d{1,2}\\u65e5\\s*-?\\s*$', '', title)
                    break

            if not title:
                # Fallback: any meaningful text inside the block (skip site name / URL fragments)
                segments = re.findall(r'>([^<]{8,})<', block)
                for seg in segments:
                    seg = seg.strip()
                    if (seg and 'svg' not in seg.lower()
                            and 'path' not in seg.lower()
                            and not seg.startswith('›')
                            and '.' not in seg[:10]):  # skip URL fragments
                        title = self._decode_entities(seg[:120])
                        break

            # Description: various possible containers
            desc = ''
            for desc_pat in (
                r'class="[^"]*snippet-description[^"]*"[^>]*>(.*?)</(?:div|p|span)>',
                r'class="[^"]*snippet-content[^"]*"[^>]*>(.*?)</(?:div|p|span)>',
            ):
                desc_m = re.search(desc_pat, block, re.DOTALL | re.IGNORECASE)
                if desc_m:
                    desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
                    desc = self._decode_entities(desc)
                    break
            
            # If no snippet-description, pull from text paragraphs
            if not desc:
                segments = re.findall(r'>([^<]{20,})<', block)
                for seg in segments:
                    seg = seg.strip()
                    # Skip the title itself, URL breadcrumbs, SVG data
                    if (seg and seg != title
                            and 'svg' not in seg.lower()
                            and not seg.startswith('›')
                            and not re.match('^[\\d\\u5e74\\u6708\\u65e5\\s\\-]+$', seg)):
                        desc = self._decode_entities(seg[:300])
                        break
            
            results.append({
                'title': self._decode_entities(title) if title else '(no title)',
                'url': url,
                'snippet': desc[:300],
            })
            if len(results) >= max_results:
                break
        
        return results

    # ---------- DuckDuckGo ----------

    def _search_duckduckgo(self, query: str, max_results: int, timeout: int) -> Dict[str, Any]:
        """Search via DuckDuckGo (HTML lite version, fallback)."""
        if not HAS_REQUESTS:
            return {"success": False, "error": "requests not installed", "results": []}
        
        try:
            response = requests.post(
                self.DUCKDUCKGO_URL,
                data={'q': query, 'b': '', 'kl': 'cn-zh'},
                headers=self._HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            page_html = self._fix_encoding(response)
            results = self._parse_duckduckgo_html(page_html, max_results)
            
            if results:
                return {"success": True, "query": query, "results": results, "source": "DuckDuckGo"}
            return {"success": False, "error": "DDG returned page but no results parsed", "results": []}
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}
    
    def _parse_duckduckgo_html(self, page_html: str, max_results: int) -> List[Dict[str, str]]:
        """Parse DuckDuckGo HTML search results (compatible with multiple page structures)."""
        from urllib.parse import unquote, parse_qs, urlparse
        results = []

        # Pattern 1: class="result__a" (classic version)
        pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, page_html, re.IGNORECASE | re.DOTALL)

        # Pattern 2: lite version <a rel="nofollow">
        if not matches:
            pattern = r'<a[^>]*rel="nofollow"[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>'
            matches = re.findall(pattern, page_html, re.IGNORECASE | re.DOTALL)
        
        for url, raw_title in matches[:max_results]:
            if not url or 'duckduckgo.com' in url:
                continue
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            title = self._decode_entities(title)
            if not title:
                continue
            
            real_url = url
            if 'uddg=' in url:
                try:
                    parsed = urlparse(url)
                    params = parse_qs(parsed.query)
                    if 'uddg' in params:
                        real_url = unquote(params['uddg'][0])
                except Exception:
                    pass
            
            results.append({"title": title, "url": real_url, "snippet": ""})
        
        # Extract snippets
        for pat in (r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>'):
            snippet_matches = re.findall(pat, page_html, re.IGNORECASE | re.DOTALL)
            if snippet_matches:
                for i, raw in enumerate(snippet_matches[:len(results)]):
                    clean = re.sub(r'<[^>]+>', '', raw).strip()
                    clean = self._decode_entities(clean)
                    if clean:
                        results[i]["snippet"] = clean[:300]
                break
        
        return results
    
    # (Bing API removed -- requires a paid Azure key, not practical)

    # ------------------------------------------------------------------
    # Page fetch (trafilatura preferred -> regex fallback + page cache)
    # ------------------------------------------------------------------

    def fetch_page_content(self, url: str, max_lines: int = 80,
                           start_line: int = 1, timeout: int = 15) -> Dict[str, Any]:
        """Fetch page content (trafilatura main-text extraction + line-based pagination).

        Args:
            url: Page URL
            max_lines: Max lines per page
            start_line: Starting line (1-based), used for pagination
            timeout: Request timeout in seconds
        """
        if not HAS_REQUESTS:
            return {"success": False, "error": "The 'requests' library must be installed"}

        try:
            # --- Page cache lookup (reuse fetched content across pages) ---
            cached = self._page_cache.get(url)
            if cached:
                ts, cached_lines = cached
                if (time.time() - ts) < self._PAGE_CACHE_TTL:
                    return self._paginate_lines(url, cached_lines, start_line, max_lines)

            response = requests.get(url, headers=self._HEADERS, timeout=timeout)
            response.raise_for_status()

            # Fix encoding (core mojibake prevention)
            page_html = self._fix_encoding(response)

            # --- Main-text extraction: trafilatura preferred, regex fallback ---
            text = None
            if self._HAS_TRAFILATURA:
                try:
                    import trafilatura
                    text = trafilatura.extract(
                        page_html,
                        include_comments=False,
                        include_tables=True,
                        output_format='txt',
                        favor_recall=True,
                    )
                except Exception:
                    text = None

            if not text:
                # Fall back to regex tag stripping
                text = self._fallback_html_to_text(page_html)

            # Clean: collapse whitespace within each line, keep newline structure
            lines = []
            for line in text.split('\n'):
                cleaned = re.sub(r'[ \t]+', ' ', line).strip()
                if cleaned:
                    lines.append(cleaned)

            # Cache this page (reused when paging)
            self._page_cache[url] = (time.time(), lines)
            # Cap cache size
            if len(self._page_cache) > 50:
                oldest_key = min(self._page_cache, key=lambda k: self._page_cache[k][0])
                del self._page_cache[oldest_key]

            return self._paginate_lines(url, lines, start_line, max_lines)

        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    def _fallback_html_to_text(self, page_html: str) -> str:
        """Regex tag-strip fallback (used when trafilatura is unavailable)."""
        # Remove non-content blocks
        for tag in ('script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript'):
            page_html = re.sub(
                rf'<{tag}[^>]*>.*?</{tag}>',
                '', page_html, flags=re.DOTALL | re.IGNORECASE,
            )
        # Block-level tags -> newline
        page_html = re.sub(r'<br\s*/?\s*>', '\n', page_html, flags=re.IGNORECASE)
        page_html = re.sub(
            r'</(?:p|div|li|tr|td|th|h[1-6]|blockquote|section|article)>',
            '\n', page_html, flags=re.IGNORECASE,
        )
        # Strip remaining HTML tags
        text = re.sub(r'<[^>]+>', ' ', page_html)
        # Decode HTML entities
        return self._decode_entities(text)

    @staticmethod
    def _paginate_lines(url: str, lines: List[str], start_line: int, max_lines: int) -> Dict[str, Any]:
        """Paginate over an already-extracted list of lines."""
        total_lines = len(lines)
        offset = max(0, start_line - 1)
        page_lines = lines[offset:offset + max_lines]
        end_line = offset + len(page_lines)

        if not page_lines:
            return {
                "success": True,
                "url": url,
                "content": f"[End of page] This page has {total_lines} lines, start_line={start_line} is out of range."
            }

        content = '\n'.join(page_lines)

        if end_line < total_lines:
            next_start = end_line + 1
            content += (
                f"\n\n[Pagination] Showing lines {offset+1}-{end_line} of {total_lines}."
                f" For more, call fetch_webpage(url=\"{url}\", start_line={next_start})."
            )
        else:
            content += f"\n\n[All content shown] Lines {offset+1}-{end_line} of {total_lines}."

        return {"success": True, "url": url, "content": content}


# ============================================================
# Houdini tool definitions
# ============================================================

HOUDINI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_wrangle_node",
            "description": "[PREFERRED] Create a Wrangle node and set its VEX code. This is the first-choice method for geometry processing — if VEX can solve it, use this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vex_code": {
                        "type": "string",
                        "description": "VEX code body. Common syntax: @P (position), @N (normal), @Cd (color), @pscale (point size), addpoint(), addprim(), addvertex(), etc."
                    },
                    "wrangle_type": {
                        "type": "string",
                        "enum": ["attribwrangle", "pointwrangle", "primitivewrangle", "volumewrangle", "vertexwrangle"],
                        "description": "Wrangle type. Default 'attribwrangle' (most general). pointwrangle for points, primitivewrangle for primitives."
                    },
                    "node_name": {
                        "type": "string",
                        "description": "Node name (optional)"
                    },
                    "run_over": {
                        "type": "string",
                        "enum": ["Points", "Vertices", "Primitives", "Detail", "Numbers"],
                        "description": "Run mode (matches Houdini class): Points=2 (default), Vertices=3, Primitives=1, Detail=0 (global), Numbers=4 (iteration count)"
                    },
                    "parent_path": {
                        "type": "string",
                        "description": "Parent network path (optional, empty = current network)"
                    }
                },
                "required": ["vex_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_structure",
            "description": "Get the network structure. If NetworkBox groups exist, returns a box-level overview (name + comment + node count) by default to save context; pass box_name to drill into a specific box's nodes. Without NetworkBox, returns all nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "network_path": {
                        "type": "string",
                        "description": "Network path e.g. '/obj/geo1', empty = current network"
                    },
                    "box_name": {
                        "type": "string",
                        "description": "Specify a NetworkBox name to view its inner nodes and connections. Empty = overview (box summary + ungrouped nodes)."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (starts at 1) for paging through results"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_parameters",
            "description": "Get full parameter list and node overview: type, state flags (display/render/bypass), errors, input/output connections, and per-parameter internal name, type (Float/Int/Menu etc.), label, default, current value, menu options. MUST call this before set_parameters to confirm correct param name and type — do not guess. Supports pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {
                        "type": "string",
                        "description": "Full node path e.g. '/obj/geo1/box1'"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (starts at 1) for paging through parameters"
                    }
                },
                "required": ["node_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_node_parameter",
            "description": "Set a node parameter value. NOTE: call get_node_parameters first to confirm the param name and type — do not guess.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string", "description": "Node path"},
                    "param_name": {"type": "string", "description": "Parameter name (must be a valid name returned by get_node_parameters)"},
                    "value": {
                        "type": ["string", "number", "boolean", "array"],
                        "items": {"type": ["string", "number", "boolean"]},
                        "description": "Parameter value (scalar or array, e.g. vector [1, 0, 0])"
                    }
                },
                "required": ["node_path", "param_name", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "Create a single node. Type format: 'box' or 'sop/box' (just the node name like 'box' is fine — category is auto-detected). On failure, MUST call search_node_types to find the correct type name before retrying.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string", 
                        "description": "Node type name, e.g. 'box', 'scatter', 'noise'. Plain node name is fine — category is auto-detected (sop/obj/etc.)."
                    },
                    "node_name": {"type": "string", "description": "Node name (optional), auto-generated if omitted"},
                    "parameters": {"type": "object", "description": "Initial parameter dict (optional), e.g. {'size': 1.0}"},
                    "parent_path": {"type": "string", "description": "Parent network path (optional), e.g. '/obj/geo1', empty = current network"}
                },
                "required": ["node_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_nodes_batch",
            "description": "Create nodes in batch and auto-connect them. Each element in 'nodes' needs an id (temporary identifier) and type. 'connections' specifies links using ids from 'nodes'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string"},
                                "name": {"type": "string"},
                                "parms": {"type": "object"}
                            },
                            "required": ["id", "type"]
                        }
                    },
                    "connections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "input": {"type": "integer"}
                            }
                        }
                    }
                },
                "required": ["nodes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "connect_nodes",
            "description": "Connect two nodes. Call get_node_inputs first to understand the target's input ports. input_index: 0=first, 1=second (e.g. copytopoints target points), 2=third.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_path": {"type": "string", "description": "Upstream node path (provides data)"},
                    "to_path": {"type": "string", "description": "Downstream node path (receives data)"},
                    "input_index": {"type": "integer", "description": "Target node input index. 0=main, 1=second (e.g. copy's target points), 2=third. Default 0"}
                },
                "required": ["from_path", "to_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_node",
            "description": "Delete a node at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string", "description": "Full path of the node to delete, e.g. '/obj/geo1/box1'"}
                },
                "required": ["node_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_node_types",
            "description": "Search Houdini-available node types by keyword. For precise type lookup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search keyword, e.g. 'scatter', 'copy'"},
                    "category": {"type": "string", "enum": ["sop", "obj", "dop", "vop", "cop", "all"], "description": "Node category, default 'all'"},
                    "limit": {"type": "integer", "description": "Max results, default 10"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search_nodes",
            "description": "Find a suitable node type from a natural-language description. e.g. 'I need to scatter points on a surface' finds scatter. Use when unsure which node to pick.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Describe the functionality in natural language, e.g. 'scatter points on a surface', 'copy objects onto points', 'noise deformation'"
                    },
                    "category": {"type": "string", "enum": ["sop", "obj", "dop", "vop", "all"], "description": "Node category, default 'sop'"}
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_children",
            "description": "List all child nodes in a network — like the 'ls' command. Shows name, type, and state. Supports pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "network_path": {"type": "string", "description": "Network path, e.g. '/obj/geo1'. Empty = current network"},
                    "recursive": {"type": "boolean", "description": "Recursively list subnets, default false"},
                    "show_flags": {"type": "boolean", "description": "Show node flags (display/render/bypass), default true"},
                    "page": {"type": "integer", "description": "Page number (starts at 1) for paging"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_selection",
            "description": "Read details of currently-selected nodes. No node path needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_params": {"type": "boolean", "description": "Include parameter details, default true"},
                    "include_geometry": {"type": "boolean", "description": "Include geometry info, default false"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_display_flag",
            "description": "Set node display flag — controls which node is shown in the viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string", "description": "Node path"},
                    "display": {"type": "boolean", "description": "Set as display node"},
                    "render": {"type": "boolean", "description": "Set as render node"}
                },
                "required": ["node_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "copy_node",
            "description": "Copy/clone a node to a new location. Can copy within or across networks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Source node path"},
                    "dest_network": {"type": "string", "description": "Destination network path; leave blank to copy within the same network"},
                    "new_name": {"type": "string", "description": "New node name (optional)"}
                },
                "required": ["source_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_set_parameters",
            "description": "Batch-modify parameters across multiple nodes (like search_replace).",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of node paths"
                    },
                    "param_name": {"type": "string", "description": "Parameter name"},
                    "value": {
                        "type": ["string", "number", "boolean", "array"],
                        "items": {"type": ["string", "number", "boolean"]},
                        "description": "New value (scalar or array)"
                    }
                },
                "required": ["node_paths", "param_name", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_nodes_by_param",
            "description": "Search nodes by parameter value within a network (like grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "network_path": {"type": "string", "description": "Network path to search; empty = current network"},
                    "param_name": {"type": "string", "description": "Parameter name"},
                    "value": {"type": ["string", "number"], "description": "Value to match (optional; empty = list all nodes that have this parameter)"},
                    "recursive": {"type": "boolean", "description": "Recursively search subnets, default true"}
                },
                "required": ["param_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_hip",
            "description": "Save the current HIP file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Save path (optional; empty = save to current file)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_redo",
            "description": "Perform undo or redo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["undo", "redo"], "description": "Operation type"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Web search for anything (weather, news, docs, Houdini help, programming questions, general knowledge).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results, default 5"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch web page content from a URL (line-paginated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Page URL"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line (default 1) for paging"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_doc",
            "description": "Search the local Houdini doc index (nodes/VEX/HOM).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "Keyword: node name, VEX function, or HOM class"
                    },
                    "top_k": {
                        "type": "integer", 
                        "description": "Return top-k results (default 5)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_houdini_node_doc",
            "description": "Get node help docs (paginated). Auto-fallback: local help -> SideFX online -> node type info. Prefer get_node_inputs for input port info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Node type name"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["sop", "obj", "dop", "vop", "cop", "rop"],
                        "description": "Node category, default 'sop'"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (starts at 1)"
                    }
                },
                "required": ["node_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute code in Houdini Python Shell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number for paging long output"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a command in the system shell (NOT Houdini Python Shell). Run pip, git, dir/ls, ffmpeg, ssh, scp, etc. Working dir defaults to project root. Timeout: default 30s, max 120s. Dangerous commands (recursive deletes, format, etc.) are blocked. Notes: 1) emit a complete runnable command, no placeholders; 2) interactive commands must use non-interactive flags; 3) prefer precise commands to minimize output (e.g. find -maxdepth 2); 4) wrap paths with spaces in quotes; 5) on failure, analyze stderr and fix before retrying.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (optional)"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30, max 120)"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number for paging long output"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_errors",
            "description": "Check Houdini node cooking errors and warnings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {
                        "type": "string",
                        "description": "Node or network path to check; empty = current network"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_inputs",
            "description": "[CALL BEFORE CONNECTING] Get node input port info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Node type name, e.g. 'copytopoints', 'boolean', 'scatter'"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["sop", "obj", "dop", "vop"],
                        "description": "Node category, default 'sop'"
                    }
                },
                "required": ["node_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": "Add a task to the Todo list. Use this BEFORE starting complex tasks to lay out the plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "Unique task ID, e.g. 'step1', 'task_create_box'"
                    },
                    "text": {
                        "type": "string",
                        "description": "Task description"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "error"],
                        "description": "Task status, default 'pending'"
                    }
                },
                "required": ["todo_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update a Todo task's status. MUST call immediately after each step is finished — do not batch updates at the end.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "Task ID to update"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "error"],
                        "description": "New status"
                    }
                },
                "required": ["todo_id", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_and_summarize",
            "description": "[CALL BEFORE FINISHING] Verify the node network and summarize. Auto-checks: 1) isolated nodes, 2) error nodes, 3) connection integrity, 4) display flags. get_network_structure is built-in — no need to call it separately first. If problems are found, fix them and call again until it passes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of items to check (e.g. node names)"
                    },
                    "expected_result": {
                        "type": "string",
                        "description": "Expected outcome description"
                    }
                },
                "required": ["check_items", "expected_result"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": "Execute a predefined Skill (advanced analysis script). Skills are optimized special-purpose scripts — more reliable than hand-written execute_python. Use list_skills to see what's available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name (use list_skills to get)"
                    },
                    "params": {
                        "type": "object",
                        "description": "Arguments passed to the Skill (key/value)"
                    }
                },
                "required": ["skill_name", "params"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all available Skills and their parameter docs. Before doing complex analysis (geometry attribute stats, batch checks, etc.), call this to see if a Skill already exists.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    # ============================================================
    # Node layout tools -- auto-arrange node positions
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "layout_nodes",
            "description": "Auto-layout node positions. Call after verify_and_summarize passes and before creating NetworkBox to keep nodes tidy. Strategies: auto (smart), grid, columns (by topological depth).",
            "parameters": {
                "type": "object",
                "properties": {
                    "network_path": {
                        "type": "string",
                        "description": "Parent network path (e.g. /obj/geo1). Empty = current active network."
                    },
                    "node_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of full node paths to lay out. Empty = lay out all children of the network."
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "grid", "columns"],
                        "description": "Layout method. auto=smart (recommended), grid=grid layout, columns=by topological depth. Default auto."
                    },
                    "spacing": {
                        "type": "number",
                        "description": "Node spacing multiplier, default 1.0. Larger = more spacing between nodes."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_positions",
            "description": "Get node position info (coords, type) — for inspecting layout results or current state during manual tweaks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "network_path": {
                        "type": "string",
                        "description": "Parent network path (e.g. /obj/geo1). Empty = current active network."
                    },
                    "node_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of full node paths to query. Empty = return positions of all children in the network."
                    }
                },
                "required": []
            }
        }
    },
    # ============================================================
    # NetworkBox tools -- node grouping and visual organization
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "create_network_box",
            "description": "Create a NetworkBox (node group). Set name, comment, and color preset; can include nodes at creation time. Use after finishing each logical stage to group its nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {
                        "type": "string",
                        "description": "Parent network path (e.g. /obj/geo1). Empty = current active network."
                    },
                    "name": {
                        "type": "string",
                        "description": "NetworkBox name (e.g. input_stage, deform_stage). Empty = auto-generate."
                    },
                    "comment": {
                        "type": "string",
                        "description": "Comment text shown on the NetworkBox title bar (e.g. 'Data input', 'Noise deformation')."
                    },
                    "color_preset": {
                        "type": "string",
                        "enum": ["input", "processing", "deform", "output", "simulation", "utility"],
                        "description": "Color preset: input (blue), processing (green), deform (orange), output (red), simulation (purple), utility (gray)."
                    },
                    "node_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of full node paths to include in the box. The box auto-resizes to contain them."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_nodes_to_box",
            "description": "Add nodes to an existing NetworkBox. Use after creating new nodes to group them appropriately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {
                        "type": "string",
                        "description": "Parent network path (e.g. /obj/geo1). Empty = current active network."
                    },
                    "box_name": {
                        "type": "string",
                        "description": "Target NetworkBox name."
                    },
                    "node_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of full node paths to add."
                    },
                    "auto_fit": {
                        "type": "boolean",
                        "description": "Auto-resize the box to fit all nodes. Default true."
                    }
                },
                "required": ["box_name", "node_paths"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_network_boxes",
            "description": "List all NetworkBoxes in a network along with their contained nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {
                        "type": "string",
                        "description": "Network path to query (e.g. /obj/geo1). Empty = current active network."
                    }
                },
                "required": []
            }
        }
    },
    # ============================================================
    # PerfMon performance profiling tools
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "perf_start_profile",
            "description": "Start Houdini performance profiling (via hou.perfMon). For detailed cook timing and memory analysis. After starting, perform actions (e.g. force cook), then call perf_stop_and_report. For quick cook-time ranking, prefer run_skill(skill_name='analyze_cook_performance').",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Profile title (optional, default 'AI Performance Analysis')"
                    },
                    "force_cook_node": {
                        "type": "string",
                        "description": "Node path to force-cook immediately after starting profile (optional). Pass a terminal node path to cook the whole chain."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perf_stop_and_report",
            "description": "Stop performance profiling and return a report. perf_start_profile must have been called first. Report includes cook-time ranking, memory stats. Optionally saves a .hperf file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "save_path": {
                        "type": "string",
                        "description": "Path to save .hperf profile file (optional), e.g. 'C:/tmp/profile.hperf'"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (starts at 1) for paging long reports"
                    }
                },
                "required": []
            }
        }
    },
    # ★ Long-term memory active search tool
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search the long-term memory store. Use to recall past experiences, user preferences, gotchas, debugging tips, common commands. Filterable by category. Results include confidence scores — treat as advisory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or question"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["preference", "command", "debug", "pitfall", "workflow", "knowledge", "user_profile", "general"],
                        "description": "Filter by category (optional)"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results, default 5, max 10"
                    }
                },
                "required": ["query"]
            }
        }
    },
    # ★ Viewport screenshot tool (visual verification)
    {
        "type": "function",
        "function": {
            "name": "capture_viewport",
            "description": "Capture a snapshot of the current Houdini 3D viewport. Use to verify node output, check geometry, validate materials/lighting, etc. The image is automatically passed to you for visual analysis. Recommended after key operations to confirm the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {
                        "type": "integer",
                        "description": "Screenshot width (pixels), default 960, range 160-1920"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Screenshot height (pixels), default 540, range 120-1080"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional: save screenshot to a file path (e.g. $HIP/snapshot.jpg). If omitted, the image is only sent to the model for visual analysis."
                    }
                },
                "required": []
            }
        }
    }
]

# ★ Register core tools to ToolRegistry (runs automatically when the module loads)
try:
    from .tool_registry import get_tool_registry as _get_reg
    _reg = _get_reg()
    if not _reg.initialized:
        _reg.register_core_tools(HOUDINI_TOOLS)
except Exception as _e:
    _dbg(f"[AIClient] ToolRegistry register failed (non-fatal): {_e}")


# ============================================================
# AI Client
# ============================================================

class AIClient:
    """AI client with streaming, Function Calling, and web search support."""

    OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    OLLAMA_API_URL = "http://localhost:11434/v1/chat/completions"  # Ollama OpenAI-compatible endpoint
    DUOJIE_API_URL = "https://api.duojie.games/v1/chat/completions"  # Duojie proxy (OpenAI protocol)
    DUOJIE_ANTHROPIC_API_URL = "https://api.duojie.games/v1/messages"  # Duojie proxy (Anthropic protocol)
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"  # OpenRouter (OpenAI-compatible)

    # Additional built-in providers. All are OpenAI-compatible (Bearer key,
    # /chat/completions, standard GET /models discovery), so adding one here
    # automatically wires its URL, display name, API-key handling, and live
    # model auto-fetch — no hardcoded model lists. 'anthropic' is handled
    # separately below because it speaks the native Anthropic Messages protocol.
    _EXTRA_PROVIDERS = {
        'gemini':     {'name': 'Google Gemini',  'url': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'},
        'xai':        {'name': 'xAI (Grok)',      'url': 'https://api.x.ai/v1/chat/completions'},
        'groq':       {'name': 'Groq',            'url': 'https://api.groq.com/openai/v1/chat/completions'},
        'mistral':    {'name': 'Mistral',         'url': 'https://api.mistral.ai/v1/chat/completions'},
        'moonshot':   {'name': 'Moonshot (Kimi)', 'url': 'https://api.moonshot.ai/v1/chat/completions'},
        'together':   {'name': 'Together AI',     'url': 'https://api.together.xyz/v1/chat/completions'},
        'perplexity': {'name': 'Perplexity',      'url': 'https://api.perplexity.ai/chat/completions'},
        'opencode':   {'name': 'OpenCode Zen',    'url': 'https://opencode.ai/zen/v1/chat/completions'},
    }
    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

    # Duojie models that use the Anthropic protocol (GLM series, etc.)
    _DUOJIE_ANTHROPIC_MODELS = frozenset({'glm-4.7', 'glm-5', 'glm-5-turbo', 'glm-5.1'})

    # ★ Pre-compiled stream content cleanup regex (avoids re-compiling on every SSE chunk)
    _RE_CLEAN_PATTERNS = [
        re.compile(r'</?tool_call[^>]*>'),
        re.compile(r'<arg_key>([^<]+)</arg_key>\s*<arg_value>([^<]+)</arg_value>'),
        re.compile(r'</?arg_key[^>]*>'),
        re.compile(r'</?arg_value[^>]*>'),
        re.compile(r'</?redacted_reasoning[^>]*>'),
    ]

    # Custom provider runtime config — the original single-slot fields stay
    # exactly as-is for provider id 'custom' (used by the old Qt panel's
    # Custom Provider dialog, untouched). Any additional custom endpoints
    # ("Add Provider" in the web Settings) live in _extra_custom_providers,
    # keyed by their own id (e.g. 'custom_2'). _custom_cfg()/_is_custom_provider()
    # is the single place that reads either one, so every other call site
    # below only ever goes through those two helpers.
    _CUSTOM_API_URL: str = ''
    _CUSTOM_SUPPORTS_FC: bool = True

    def _is_custom_provider(self, provider: str) -> bool:
        return provider == 'custom' or provider in self._extra_custom_providers

    def _custom_cfg(self, provider: str) -> Dict[str, Any]:
        if provider == 'custom':
            return {'api_url': self._CUSTOM_API_URL, 'supports_fc': self._CUSTOM_SUPPORTS_FC}
        return self._extra_custom_providers.get(provider, {'api_url': '', 'supports_fc': True})

    def add_custom_provider(self, provider_id: str, api_url: str = '', api_key: str = '', supports_fc: bool = True):
        """Register (or update) an additional custom OpenAI-compatible endpoint
        beyond the original single 'custom' slot — see the class comment above."""
        self._extra_custom_providers[provider_id] = {'api_url': (api_url or '').strip(), 'supports_fc': supports_fc}
        if api_key:
            self._api_keys[provider_id] = api_key.strip()

    def remove_custom_provider(self, provider_id: str):
        self._extra_custom_providers.pop(provider_id, None)
        self._api_keys.pop(provider_id, None)

    def __init__(self, api_key: Optional[str] = None):
        self._extra_custom_providers: Dict[str, Dict[str, Any]] = {}
        self._api_keys: Dict[str, Optional[str]] = {
            'openai': api_key or self._read_api_key('openai'),
            'deepseek': self._read_api_key('deepseek'),
            'glm': self._read_api_key('glm'),
            'ollama': 'ollama',  # Ollama doesn't need a real API key, just a non-empty value
            'duojie': self._read_api_key('duojie'),
            'openrouter': self._read_api_key('openrouter'),
            'anthropic': self._read_api_key('anthropic'),
            'custom': self._read_api_key('custom'),
        }
        # Extra built-in providers (Gemini, Groq, xAI, Mistral, ...): load any
        # stored/env key the same way, keyed by their own id.
        for _pid in self._EXTRA_PROVIDERS:
            self._api_keys[_pid] = self._read_api_key(_pid)
        self._ssl_context = self._create_ssl_context()
        self._web_searcher = WebSearcher()
        self._tool_executor: Optional[Callable[[str, dict], dict]] = None
        self._batch_tool_executor: Optional[Callable[[list], list]] = None

        # Ollama config
        self._ollama_base_url = "http://localhost:11434"

        # Network config
        self._max_retries = 3
        self._retry_delay = 1.0
        self._chunk_timeout = 60  # Ollama local models can be slow, raise timeout

        # ★ Persistent HTTP session (connection pool + keep-alive, avoids TLS handshake per round)
        self._http_session = requests.Session()
        self._http_session.headers.update({
            'Content-Type': 'application/json',
        })

        # Stop control (threading.Event for thread safety)
        import threading
        self._stop_event = threading.Event()

    def request_stop(self):
        """Request that the current request stops (thread-safe)."""
        self._stop_event.set()

    def reset_stop(self):
        """Reset the stop flag (thread-safe)."""
        self._stop_event.clear()

    def is_stop_requested(self) -> bool:
        """Check whether a stop has been requested (thread-safe)."""
        return self._stop_event.is_set()

    def set_tool_executor(self, executor: Callable[..., dict]):
        """Set the tool executor.

        executor signature: (tool_name: str, **kwargs) -> dict
        """
        self._tool_executor = executor

    def set_batch_tool_executor(self, executor: Callable[[list], list]):
        """Set the batch tool executor (used for parallel batching of read-only tools).

        executor signature: (batch: [(tool_name, kwargs), ...]) -> [result_dict, ...]
        If unset, batch execution falls back to calling _tool_executor one at a time.
        """
        self._batch_tool_executor = executor

    # ----------------------------------------------------------
    # Tool result pagination: split by lines, let the AI decide if it needs more
    # ----------------------------------------------------------

    # Query-type and operation-type tool classifications (shared constants)
    _QUERY_TOOLS = frozenset({
        'get_network_structure', 'get_node_parameters',
        'list_children',
        'read_selection', 'search_node_types',
        'semantic_search_nodes', 'find_nodes_by_param', 'check_errors',
        'search_local_doc', 'get_houdini_node_doc', 'get_node_inputs',
        'execute_python', 'execute_shell', 'web_search', 'fetch_webpage',
        'run_skill', 'list_skills',
        'capture_viewport',
    })
    _OP_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'connect_nodes',
        'set_node_parameter', 'create_wrangle_node',
    })

    @staticmethod
    def _paginate_result(text: str, max_lines: int = 50) -> str:
        """Paginate tool result by lines, truncating overflow with a pagination hint.

        - If under max_lines, return as-is
        - Otherwise keep the first max_lines and append a pagination note

        Args:
            text: Raw tool output text
            max_lines: Max lines per page (default 50)

        Returns:
            Paginated text
        """
        if not text:
            return text
        lines = text.split('\n')
        total = len(lines)
        if total <= max_lines:
            return text
        page = '\n'.join(lines[:max_lines])
        return (
            f"{page}\n\n"
            f"[Pagination] Showing lines 1-{max_lines} of {total} (truncated)."
            f" If the current info is enough, use it directly."
            f" Note: calling again with the same arguments returns the same result."
            f" For more, refine the query, or use fetch_webpage to load a specific URL (supports start_line paging)."
        )

    # ------------------------------------------------------------------
    # Message sanitization: ensure messages sent to the API are well-formed
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tool_call_ids(tool_calls: list) -> list:
        """Ensure every tool_call has a valid id field.

        Proxy APIs (e.g. Duojie) sometimes omit tool_call_id in the first chunk,
        leaving subsequent role:tool messages with empty tool_call_id -> API 400.
        """
        import uuid
        for tc in tool_calls:
            if not tc.get('id'):
                tc['id'] = f"call_{uuid.uuid4().hex[:24]}"
            # Ensure the type field exists
            if not tc.get('type'):
                tc['type'] = 'function'
            # Ensure the function field is complete
            fn = tc.get('function', {})
            if not fn.get('name'):
                fn['name'] = 'unknown'
            if not fn.get('arguments', '').strip():
                fn['arguments'] = '{}'
            tc['function'] = fn
        return tool_calls

    # ----------------------------------------------------------
    # Smart summarization: extract the key info from tool results
    # ----------------------------------------------------------

    _PATH_RE = re.compile(r'/(?:obj|out|stage|tasks|ch|shop|img|mat|vex)/[\w/]+')
    _COUNT_RE = re.compile(r'(?:nodecount|pointcount|errorcount|warningcount|count|total)[: :\s]*(\d+)', re.IGNORECASE)

    @classmethod
    def _summarize_tool_content(cls, content: str, max_len: int = 200) -> str:
        """Smart-summarize a tool result -- extract key info rather than blindly truncate.

        Extraction priority: paths > numeric stats > first-line summary > truncation
        """
        if not content or len(content) <= max_len:
            return content

        parts = []

        # 1. Extract node paths
        paths = cls._PATH_RE.findall(content)
        if paths:
            unique_paths = list(dict.fromkeys(paths))[:5]  # dedupe, preserve order
            parts.append("Paths: " + ", ".join(unique_paths))

        # 2. Extract count info
        counts = cls._COUNT_RE.findall(content)
        if counts:
            parts.append("Stats: " + ", ".join(counts[:4]))

        # 3. Detect success/failure state
        # noqa: CN — kept for API error detection from non-English server responses
        if 'error' in content[:100] or 'error' in content[:100].lower():
            # Error info -- keep more content
            first_line = content.split('\n', 1)[0][:200]
            parts.append(first_line)
        elif not parts:
            # No structured info extracted, keep first line
            first_line = content.split('\n', 1)[0][:150]
            parts.append(first_line)

        summary = " | ".join(parts)
        if len(summary) > max_len:
            summary = summary[:max_len]
        return summary + '...[summary]'

    # ----------------------------------------------------------
    # Image content stripping
    # ----------------------------------------------------------

    @staticmethod
    def _strip_image_content(messages: list, keep_recent_user: int = 0) -> int:
        """In-place: strip image_url content from messages, converting multimodal content to plain text.

        Args:
            messages: Message list (modified in place)
            keep_recent_user: Keep images on the N most-recent user messages (0 = strip all)

        Returns:
            Number of images stripped
        """
        stripped = 0

        # Find the indices of the N most-recent user messages (scanning backwards)
        protected_indices: set = set()
        if keep_recent_user > 0:
            count = 0
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get('role') == 'user':
                    protected_indices.add(i)
                    count += 1
                    if count >= keep_recent_user:
                        break

        for idx, msg in enumerate(messages):
            content = msg.get('content')
            if not isinstance(content, list):
                continue
            if idx in protected_indices:
                continue

            # Multimodal content: [{"type":"text","text":"..."},{"type":"image_url",...}]
            text_parts = []
            has_image = False
            for part in content:
                if isinstance(part, dict):
                    if part.get('type') == 'text':
                        text_parts.append(part.get('text', ''))
                    elif part.get('type') == 'image_url':
                        has_image = True
                        stripped += 1
                elif isinstance(part, str):
                    text_parts.append(part)

            if has_image:
                combined = '\n'.join(t for t in text_parts if t)
                if combined:
                    combined += '\n[Image removed to save context]'
                else:
                    combined = '[Image removed]'
                msg['content'] = combined

        return stripped

    # ----------------------------------------------------------
    # Progressive trimming
    # ----------------------------------------------------------

    def _progressive_trim(self, working_messages: list, tool_calls_history: list,
                          trim_level: int = 1, supports_vision: bool = True) -> list:
        """Progressively trim the context, ramping up aggressiveness with trim_level.

        Cursor-style core principles:
        - **Never truncate the text portion of user messages**
        - **Never truncate assistant messages** (keep complete replies -- this is Cursor's key design)
        - Only compress tool results (role='tool')
        - Strip images from older rounds (base64 images are the main body-bloat culprit)
        - Trim by "rounds", keep the most-recent N full rounds
        - Oldest rounds are dropped first

        trim_level=1: light  - compress old-round tool results, keep ~70% recent rounds, strip old images
        trim_level=2: medium - keep last 3 rounds, shorter tool summaries, strip all old images
        trim_level=3+: heavy - keep last 2 rounds, aggressive tool result compression, strip all images
        """
        if not working_messages:
            return working_messages

        # -- Step 0: strip images (base64 images are the main cause of 413) --
        if not supports_vision or trim_level >= 3:
            # Non-vision model or heavy trim: strip all images
            n_stripped = self._strip_image_content(working_messages, keep_recent_user=0)
        elif trim_level == 2:
            # Medium trim: keep images only on the most-recent user message
            n_stripped = self._strip_image_content(working_messages, keep_recent_user=1)
        else:
            # Light trim: keep images on the last 2 user messages
            n_stripped = self._strip_image_content(working_messages, keep_recent_user=2)

        if n_stripped > 0:
            _dbg(f"[AI Client] Trim: stripped {n_stripped} image(s)")

        sys_msg = working_messages[0] if working_messages[0].get('role') == 'system' else None
        body = working_messages[1:] if sys_msg else working_messages[:]

        if not body:
            return working_messages

        # --- Split into rounds: user message marks the boundary ---
        rounds = []  # [[msg, msg, ...], ...]
        current_round = []
        for m in body:
            if m.get('role') == 'user' and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(m)
        if current_round:
            rounds.append(current_round)

        if trim_level <= 1:
            # Light: only compress tool results from the oldest 30% of rounds
            n_rounds = len(rounds)
            protect_n = max(3, int(n_rounds * 0.7))  # Protect most-recent 70%
            for r_idx, rnd in enumerate(rounds):
                if r_idx >= n_rounds - protect_n:
                    break
                for m in rnd:
                    c = m.get('content') or ''
                    if m.get('role') == 'tool' and isinstance(c, str) and len(c) > 300:
                        m['content'] = self._summarize_tool_content(c, 300)
                    # ★ assistant and user text fully preserved ★

            keep_rounds = max(5, int(n_rounds * 0.7))
            if n_rounds > keep_rounds:
                rounds = rounds[-keep_rounds:]

        elif trim_level == 2:
            # Medium: keep most-recent 3 rounds (not 5, avoids no-op at level 1 -> 2)
            rounds = rounds[-3:] if len(rounds) > 3 else rounds
            for r_idx, rnd in enumerate(rounds):
                if r_idx >= len(rounds) - 2:
                    break  # Don't compress tool results from the last 2 rounds
                for m in rnd:
                    c = m.get('content') or ''
                    if m.get('role') == 'tool' and isinstance(c, str) and len(c) > 150:
                        m['content'] = self._summarize_tool_content(c, 150)
                    # ★ assistant and user text fully preserved ★

        else:
            # Heavy: keep last 2 rounds, aggressively compress tool results
            rounds = rounds[-2:] if len(rounds) > 2 else rounds
            for rnd in rounds[:-1]:  # Don't compress the last round
                for m in rnd:
                    c = m.get('content') or ''
                    if m.get('role') == 'tool' and isinstance(c, str) and len(c) > 100:
                        m['content'] = self._summarize_tool_content(c, 100)
                    # ★ assistant and user text fully preserved ★

        # Reassemble
        body = [m for rnd in rounds for m in rnd]
        result = ([sys_msg] if sys_msg else []) + body

        # Recovery hint
        history_summary = ""
        if tool_calls_history:
            op_history = [h for h in tool_calls_history
                          if h['tool_name'] not in self._QUERY_TOOLS]
            if op_history:
                recent = op_history[-8:]
                lines = []
                for h in recent:
                    r = h.get('result', {})
                    status = 'ok' if (isinstance(r, dict) and r.get('success')) else 'err'
                    r_str = str(r.get('result', '') if isinstance(r, dict) else r)[:60]
                    lines.append(f"  [{status}] {h['tool_name']}: {r_str}")
                history_summary = "\nCompleted operations:\n" + "\n".join(lines)

        result.append({
            'role': 'system',
            'content': (
                f'[Context management] History was auto-trimmed (level {trim_level}).'
                f'{history_summary}'
                f'\nPlease continue with the current task. Do not mention this trim.'
            )
        })

        _dbg(f"[AI Client] Progressive trim: level={trim_level}, "
              f"messages {len(working_messages)} -> {len(result)}, "
              f"rounds {len(rounds)}")
        return result

    def _sanitize_working_messages(self, messages: list) -> list:
        """Clean up the message list before sending to the API, fixing common format issues.

        Fixes:
        1. Missing id on tool_calls inside assistant messages
        2. tool_call_id on role:tool messages not matching any assistant id
        3. Remove invalid tool messages (no matching assistant tool_call)
        """
        # Collect all valid tool_call_ids
        valid_tc_ids = set()
        for msg in messages:
            if msg.get('role') == 'assistant' and 'tool_calls' in msg:
                self._ensure_tool_call_ids(msg['tool_calls'])
                for tc in msg['tool_calls']:
                    if tc.get('id'):
                        valid_tc_ids.add(tc['id'])

        # Fix tool message tool_call_ids
        sanitized = []
        for msg in messages:
            if msg.get('role') == 'tool':
                tc_id = msg.get('tool_call_id', '')
                if not tc_id or tc_id not in valid_tc_ids:
                    # Skip orphan tool messages (no matching assistant tool_call)
                    continue
            sanitized.append(msg)
        return sanitized

    # Tools that already paginate themselves; skip extra truncation
    _SELF_PAGED_TOOLS = frozenset({
        'get_houdini_node_doc', 'get_network_structure', 'get_node_parameters',
        'list_children', 'execute_python', 'execute_shell',
    })

    def _compress_tool_result(self, tool_name: str, result: dict) -> str:
        """Unified tool-result compression (shared by both agent loops).

        Strategy:
        - Self-paginating tools -> return as-is (e.g. get_houdini_node_doc)
        - Query tools -> line-based pagination (default 50 lines)
        - Operation tools -> extract paths, keep key info
        - Other tools -> mild truncation
        - Failure -> keep full error
        """
        if result.get('success'):
            content = result.get('result', '')
            # Tools that handle their own pagination, return unchanged
            if tool_name in self._SELF_PAGED_TOOLS:
                return content
            if tool_name in self._QUERY_TOOLS:
                return self._paginate_result(content, max_lines=50)
            elif tool_name in self._OP_TOOLS:
                if len(content) > 300:
                    import re
                    paths = re.findall(r'[/\w]+(?:/[\w]+)+', content)
                    if paths:
                        content = ' '.join(paths[:5])
                        if len(content) > 300:
                            content = content[:300] + '...'
                    else:
                        content = content[:300]
                return content
            else:
                # Other tools: line-paginate but more leniently
                return self._paginate_result(content, max_lines=80)
        else:
            error = result.get('error', 'Unknown error')
            return error[:500] if len(error) > 500 else error

    # ----------------------------------------------------------
    # ★ Tiered tool result compression (smarter than _summarize_tool_content; used in context-compression stage)
    # ----------------------------------------------------------

    # Tool name -> compression hook (the assistant.tool_calls on a tool_call_id preserves the name)
    _TIERED_COMPRESS_NEVER = frozenset({'check_errors'})  # Error info is never compressed

    @classmethod
    def _tiered_compress_tool(cls, tool_name: str, content: str, max_len: int = 300) -> str:
        """Tier-compress by tool type, keeping the most useful info instead of plain truncation.

        Unlike _summarize_tool_content (generic path/count extraction), this method uses
        tool-specific compression strategies, applied during context management.
        """
        if not content or len(content) <= max_len:
            return content

        # check_errors: never compress (error messages are the highest-value feedback)
        if tool_name in cls._TIERED_COMPRESS_NEVER:
            return content

        # get_network_structure: keep node name/type/connections, drop coordinates
        if tool_name == 'get_network_structure':
            lines = content.split('\n')
            kept = []
            for line in lines:
                # Skip pure-position lines
                if re.match(r'\s*(position|position|pos)\s*[:: ]', line, re.IGNORECASE):
                    continue
                # Skip blank lines and decoration rules
                stripped = line.strip()
                if not stripped or stripped.startswith('---') or stripped.startswith('==='):
                    continue
                kept.append(line)
            result = '\n'.join(kept)
            if len(result) > max_len:
                result = result[:max_len] + '...[structure compressed]'
            return result

        # get_node_parameters: keep non-default / modified params, fold defaults
        if tool_name == 'get_node_parameters':
            lines = content.split('\n')
            kept = []
            default_count = 0
            for line in lines:
                # Fold param lines containing "default" or "(default)"
                if re.search(r'\(default\)|defaultvalue|unchanged', line, re.IGNORECASE):
                    default_count += 1
                    continue
                kept.append(line)
            if default_count > 0:
                kept.append(f'  ...({default_count} default parameters omitted)')
            result = '\n'.join(kept)
            if len(result) > max_len:
                result = result[:max_len] + '...[parameters compressed]'
            return result

        # execute_python: keep stdout, truncate traceback (keep first error line)
        if tool_name == 'execute_python':
            # If there's a traceback, only keep the final error line
            tb_idx = content.find('Traceback (most recent call last)')
            if tb_idx >= 0:
                before_tb = content[:tb_idx].strip()
                # Extract the last traceback line (the actual error)
                tb_lines = content[tb_idx:].strip().split('\n')
                error_line = tb_lines[-1] if tb_lines else ''
                result = before_tb
                if error_line:
                    result += f'\n[Error] {error_line}'
                if len(result) > max_len:
                    result = result[:max_len] + '...[compressed]'
                return result
            # No traceback: normal truncation
            if len(content) > max_len:
                return content[:max_len] + '...[output compressed]'
            return content

        # search_node_types / semantic_search_nodes: keep top-N results
        if tool_name in ('search_node_types', 'semantic_search_nodes'):
            lines = content.split('\n')
            # Keep first 5 substantive lines
            kept = [l for l in lines if l.strip()][:5]
            total = len([l for l in lines if l.strip()])
            result = '\n'.join(kept)
            if total > 5:
                result += f'\n...{total} results total, first 5 shown'
            if len(result) > max_len:
                result = result[:max_len] + '...[search results compressed]'
            return result

        # web_search: keep title + summary, drop URLs
        if tool_name == 'web_search':
            # Remove URL lines (lines starting with http:// or https://)
            lines = content.split('\n')
            kept = [l for l in lines if not re.match(r'\s*https?://', l.strip())]
            result = '\n'.join(kept)
            if len(result) > max_len:
                result = result[:max_len] + '...[search compressed]'
            return result

        # Default: generic smart summary
        return cls._summarize_tool_content(content, max_len)

    # ----------------------------------------------------------
    # ★ Stale tool result detection and marking
    # ----------------------------------------------------------

    # Tools whose results can be "overridden" by a later same-name call (query type)
    _STALEABLE_TOOLS = frozenset({
        'get_network_structure', 'get_node_parameters', 'list_children',
        'check_errors', 'get_node_inputs', 'read_selection',
    })

    @classmethod
    def _mark_stale_tool_results(cls, working_messages: list) -> int:
        """Detect and compress stale tool results.

        When the same query tool is called multiple times with the same/overlapping
        args, the earlier results are stale (the AI has fresher data). Replace early
        results with a short marker to save tokens.

        Returns:
            Number of tool results marked stale
        """
        # Build a (tool_call_id -> tool_name, key_arg) map for tool messages
        # Tool name and args have to be pulled from the assistant's tool_calls
        tc_id_to_info: Dict[str, Tuple[str, str]] = {}  # tc_id -> (tool_name, key_arg)
        for msg in working_messages:
            if msg.get('role') == 'assistant' and 'tool_calls' in msg:
                for tc in msg.get('tool_calls', []):
                    tc_id = tc.get('id', '')
                    fn = tc.get('function', {})
                    name = fn.get('name', '')
                    args_str = fn.get('arguments', '{}')
                    # Extract the key arg (usually node_path or network_path)
                    try:
                        args = json.loads(args_str)
                    except Exception:
                        args = {}
                    key_arg = args.get('node_path', '') or args.get('network_path', '') or args.get('box_name', '')
                    if tc_id and name:
                        tc_id_to_info[tc_id] = (name, key_arg)

        # Scan tool messages forward, recording the last index where each (tool_name, key_arg) appears
        latest_seen: Dict[str, int] = {}  # "(tool_name):(key_arg)" -> last message index
        tool_msg_indices = []
        for i, msg in enumerate(working_messages):
            if msg.get('role') == 'tool':
                tc_id = msg.get('tool_call_id', '')
                info = tc_id_to_info.get(tc_id)
                if info:
                    tool_msg_indices.append((i, info[0], info[1]))

        # Record last-seen positions in reverse
        for idx, tool_name, key_arg in reversed(tool_msg_indices):
            sig = f"{tool_name}:{key_arg}"
            if sig not in latest_seen:
                latest_seen[sig] = idx

        # Mark earlier duplicate queries as stale
        stale_count = 0
        for idx, tool_name, key_arg in tool_msg_indices:
            if tool_name not in cls._STALEABLE_TOOLS:
                continue
            sig = f"{tool_name}:{key_arg}"
            if sig in latest_seen and latest_seen[sig] != idx:
                # This message is not the most recent -> stale
                content = working_messages[idx].get('content', '')
                if content and not content.startswith('[Stale]'):
                    working_messages[idx]['content'] = (
                        f'[Stale] This {tool_name} result has been superseded by a later query. See the latest result.'
                    )
                    stale_count += 1

        return stale_count

    # ----------------------------------------------------------
    # ★ Proactive context compression (used inside agent_loop)
    # ----------------------------------------------------------

    @classmethod
    def _estimate_messages_tokens(cls, messages: list, tools: Optional[list] = None) -> int:
        """Quickly estimate the token count of a message list + tool definitions.

        Uses a heuristic to avoid calling tiktoken every round (perf overhead).
        """
        total = 0
        for msg in messages:
            content = msg.get('content') or ''
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        total += len(part.get('text', '')) // 3
                    elif isinstance(part, dict) and part.get('type') == 'image_url':
                        total += 765
                    elif isinstance(part, str):
                        total += len(part) // 3
            else:
                # Quick estimate: English ~4 chars/token, Chinese ~1.5 chars/token
                # Blended at ~3 chars/token
                total += len(content) // 3
            # tool_calls overhead
            tcs = msg.get('tool_calls')
            if tcs:
                for tc in tcs:
                    fn = tc.get('function', {})
                    total += len(fn.get('name', '')) + len(fn.get('arguments', '')) // 3 + 8
            total += 4  # Per-message format overhead

        # Tool definition tokens (~100-200 tokens each)
        if tools:
            for t in tools:
                fn = t.get('function', {})
                total += len(fn.get('description', '')) // 4
                params = fn.get('parameters', {})
                total += len(json.dumps(params)) // 4 if params else 0
                total += 30  # Function structure overhead

        return total

    def _smart_compress_in_loop(self, working_messages: list,
                                tool_calls_history: list,
                                context_limit: int,
                                supports_vision: bool = True) -> list:
        """Proactive context compression, invoked before each agent-loop iteration.

        Tiered strategy:
        1. Mark stale tool results -> replace with short marker
        2. Tiered compression of old-round tool results (by tool type)
        3. Strip old-round images
        4. If still over limit, trim by rounds

        Difference vs _progressive_trim:
        - _progressive_trim is reactive recovery, this method is proactive prevention
        - This method uses tiered compression instead of plain truncation
        - This method never deletes data from the most recent rounds
        """
        if not working_messages:
            return working_messages

        target = int(context_limit * 0.75)  # Compression target: 75% capacity

        # -- Step 1: mark stale tool results --
        stale_count = self._mark_stale_tool_results(working_messages)
        if stale_count > 0:
            _dbg(f"[AI Client] Marked {stale_count} stale tool result(s)")

        current = self._estimate_messages_tokens(working_messages)
        if current <= target:
            return working_messages

        # -- Step 2: strip images from older rounds --
        n_stripped = self._strip_image_content(working_messages, keep_recent_user=2)
        if n_stripped > 0:
            _dbg(f"[AI Client] Stripped {n_stripped} old image(s)")
            current = self._estimate_messages_tokens(working_messages)
            if current <= target:
                return working_messages

        # -- Step 3: tiered compression of older-round tool results --
        sys_msg = working_messages[0] if working_messages[0].get('role') == 'system' else None
        body = working_messages[1:] if sys_msg else working_messages[:]

        # Split into rounds (user message marks the boundary)
        rounds: list = []
        cur_round: list = []
        for m in body:
            if m.get('role') == 'user' and cur_round:
                rounds.append(cur_round)
                cur_round = []
            cur_round.append(m)
        if cur_round:
            rounds.append(cur_round)

        n_rounds = len(rounds)
        protect_n = max(2, n_rounds // 2)  # Protect most-recent 50% of rounds

        # Starting from the oldest rounds, apply tiered compression
        # First build a tool-name map from assistant.tool_calls
        tc_id_to_name: Dict[str, str] = {}
        for m in body:
            if m.get('role') == 'assistant' and 'tool_calls' in m:
                for tc in m.get('tool_calls', []):
                    tc_id = tc.get('id', '')
                    fn_name = tc.get('function', {}).get('name', '')
                    if tc_id and fn_name:
                        tc_id_to_name[tc_id] = fn_name

        for r_idx in range(n_rounds - protect_n):
            for m in rounds[r_idx]:
                if m.get('role') == 'tool':
                    c = m.get('content') or ''
                    if len(c) > 200:
                        # Look up the tool name (reverse lookup from tool_call_id)
                        tc_id = m.get('tool_call_id', '')
                        t_name = tc_id_to_name.get(tc_id, '')
                        m['content'] = self._tiered_compress_tool(t_name, c, 200)

        current = self._estimate_messages_tokens(
            ([sys_msg] if sys_msg else []) + [m for rnd in rounds for m in rnd]
        )
        if current <= target:
            body = [m for rnd in rounds for m in rnd]
            return ([sys_msg] if sys_msg else []) + body

        # -- Step 4: if still over the limit, try LLM summarization (when there are enough rounds) --
        if len(rounds) >= 6:
            try:
                llm_result = self._llm_summarize_history(
                    ([sys_msg] if sys_msg else []) + [m for rnd in rounds for m in rnd],
                    tool_calls_history, int(target / 0.75),  # Pass through original context_limit
                )
                llm_tokens = self._estimate_messages_tokens(llm_result)
                if llm_tokens < current:
                    return llm_result
            except Exception as e:
                _dbg(f"[AI Client] LLM summarize failed, falling back to trim: {e}")

        # -- Step 5: still over the limit -> drop the oldest rounds --
        while len(rounds) > 2 and current > target:
            rounds.pop(0)
            current = self._estimate_messages_tokens(
                ([sys_msg] if sys_msg else []) + [m for rnd in rounds for m in rnd]
            )

        body = [m for rnd in rounds for m in rnd]
        result = ([sys_msg] if sys_msg else []) + body

        # Add a trim notice
        n_dropped = n_rounds - len(rounds)
        if n_dropped > 0:
            # Insert the notice after the system message
            insert_idx = 1 if sys_msg else 0
            # Attach an operation history summary
            history_lines = []
            if tool_calls_history:
                op_history = [h for h in tool_calls_history
                              if h['tool_name'] not in self._QUERY_TOOLS]
                for h in op_history[-6:]:
                    r = h.get('result', {})
                    status = 'ok' if (isinstance(r, dict) and r.get('success')) else 'err'
                    r_str = str(r.get('result', '') if isinstance(r, dict) else r)[:50]
                    history_lines.append(f"  [{status}] {h['tool_name']}: {r_str}")

            hint = f'[Context] Auto-compressed {n_dropped} early conversation rounds to stay within the context window.'
            if history_lines:
                hint += '\nCompleted operations:\n' + '\n'.join(history_lines)
            hint += '\nPlease continue the current task; do not mention this compression.'
            result.insert(insert_idx, {'role': 'system', 'content': hint})

        _dbg(f"[AI Client] Proactive compress: {n_rounds} -> {len(rounds)} round(s), "
              f"~{self._estimate_messages_tokens(result)} tokens (target {target})")

        return result

    def _llm_summarize_history(self, working_messages: list,
                                tool_calls_history: list,
                                context_limit: int,
                                model: str = '',
                                provider: str = '') -> list:
        """Use an LLM to summarize history, replacing older rounds.

        Only invoked when _smart_compress_in_loop trim still leaves it too large.
        Uses a cheap model to avoid blocking the main agent loop for too long.

        Returns:
            The replacement message list
        """
        try:
            from morfyai.utils.token_optimizer import LLMSummarizer

            # Separate system message from body
            sys_msg = working_messages[0] if working_messages[0].get('role') == 'system' else None
            body = working_messages[1:] if sys_msg else working_messages[:]

            # Split into rounds
            rounds = []
            cur = []
            for m in body:
                if m.get('role') == 'user' and cur:
                    rounds.append(cur)
                    cur = []
                cur.append(m)
            if cur:
                rounds.append(cur)

            n_rounds = len(rounds)
            if n_rounds < 4:
                return working_messages  # Too few rounds; not worth summarizing

            # Summarize the first half (keep last 3 rounds intact)
            to_summarize = rounds[:-3]
            to_keep = rounds[-3:]

            # Pick the summary model (prefer deepseek-v4-flash, else current model)
            summary_model = 'deepseek-v4-flash'
            summary_provider = 'deepseek'
            # Check for a deepseek key
            if not self._get_api_key('deepseek'):
                summary_model = model or 'gpt-5.2'
                summary_provider = provider or 'openai'

            summary_text = LLMSummarizer.summarize_rounds(
                ai_client=self,
                rounds=to_summarize,
                model=summary_model,
                provider=summary_provider,
            )

            if not summary_text:
                _dbg("[AI Client] LLM summary generation failed, falling back to trim strategy")
                return working_messages

            # Build the new message list: system message + summary + retained recent rounds
            result = []
            if sys_msg:
                result.append(sys_msg)

            result.append({
                'role': 'system',
                'content': (
                    f'[Conversation history summary] Below is a summary of the earlier {len(to_summarize)} rounds; '
                    'please continue the current task based on this context:\n\n' + summary_text
                )
            })

            for rnd in to_keep:
                result.extend(rnd)

            new_tokens = self._estimate_messages_tokens(result)
            _dbg(f"[AI Client] LLM summary: {n_rounds} -> summary + {len(to_keep)} round(s), "
                  f"~{new_tokens} tokens")

            return result

        except Exception as e:
            _dbg(f"[AI Client] LLM summary error: {e}")
            return working_messages

    def _create_ssl_context(self):
        """Create an SSL context. Falls back to unverified mode (with warning) if verification fails."""
        try:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            return context
        except Exception as e:
            _dbg(f"[AI Client] SSL cert verification failed ({e}), falling back to unverified mode. This may pose a security risk.")
            try:
                return ssl._create_unverified_context()
            except Exception:
                return None

    def _read_api_key(self, provider: str) -> Optional[str]:
        provider = (provider or 'openai').lower()

        # Ollama doesn't need an API key
        if provider == 'ollama':
            return 'ollama'
        
        env_map = {
            'openai': ['OPENAI_API_KEY', 'DCC_AI_OPENAI_API_KEY'],
            'deepseek': ['DEEPSEEK_API_KEY', 'DCC_AI_DEEPSEEK_API_KEY'],
            'glm': ['GLM_API_KEY', 'ZHIPU_API_KEY', 'DCC_AI_GLM_API_KEY'],
            'duojie': ['DUOJIE_API_KEY', 'DCC_AI_DUOJIE_API_KEY'],
            'openrouter': ['OPENROUTER_API_KEY', 'DCC_AI_OPENROUTER_API_KEY'],
            'custom': ['CUSTOM_API_KEY', 'DCC_AI_CUSTOM_API_KEY'],
        }
        # Any provider without an explicit entry (the extra built-ins) falls
        # back to the conventional <PROVIDER>_API_KEY env var.
        env_vars = env_map.get(provider) or [
            '%s_API_KEY' % provider.upper(), 'DCC_AI_%s_API_KEY' % provider.upper()]
        for env_var in env_vars:
            key = os.environ.get(env_var)
            if key:
                return key
        cfg, _ = load_config('ai', dcc_type='houdini')
        if cfg:
            key_map = {
                'openai': 'openai_api_key', 'deepseek': 'deepseek_api_key',
                'glm': 'glm_api_key', 'duojie': 'duojie_api_key',
                'openrouter': 'openrouter_api_key',
                'custom': 'custom_api_key',
            }
            return cfg.get(key_map.get(provider, '%s_api_key' % provider)) or None
        return None

    def has_api_key(self, provider: str = 'openai') -> bool:
        provider = (provider or 'openai').lower()
        # Ollama is always available (local service)
        if provider == 'ollama':
            return True
        # Custom: available as long as URL is configured (key optional)
        if self._is_custom_provider(provider):
            return bool(self._custom_cfg(provider).get('api_url'))
        return bool(self._api_keys.get(provider))

    def _get_api_key(self, provider: str) -> Optional[str]:
        return self._api_keys.get((provider or 'openai').lower())

    def set_api_key(self, key: str, persist: bool = False, provider: str = 'openai') -> bool:
        provider = (provider or 'openai').lower()
        key = (key or '').strip()
        if not key:
            return False
        self._api_keys[provider] = key
        if persist:
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            key_map = {'openai': 'openai_api_key', 'deepseek': 'deepseek_api_key', 'glm': 'glm_api_key',
                       'duojie': 'duojie_api_key', 'openrouter': 'openrouter_api_key', 'custom': 'custom_api_key'}
            cfg[key_map.get(provider, f'{provider}_api_key')] = key
            ok, _ = save_config('ai', cfg, dcc_type='houdini')
            return ok
        return True

    def get_masked_key(self, provider: str = 'openai') -> str:
        provider = (provider or 'openai').lower()
        # Ollama shows a local status
        if provider == 'ollama':
            return 'Local'
        # Custom: show abbreviated URL
        if self._is_custom_provider(provider):
            url = self._custom_cfg(provider).get('api_url')
            if url:
                # Pull out the hostname for display
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    host = parsed.hostname or url[:20]
                    return host[:16] + ('...' if len(host) > 16 else '')
                except Exception:
                    return url[:16] + '...'
            return 'Not Set'
        key = self._get_api_key(provider)
        if not key:
            return ''
        if len(key) <= 10:
            return '*' * len(key)
        return key[:5] + '...' + key[-4:]

    def _is_anthropic_protocol(self, provider: str, model: str) -> bool:
        """Return whether to use the Anthropic Messages protocol (vs. OpenAI protocol)."""
        if provider == 'anthropic':
            return True
        return provider == 'duojie' and model.lower() in self._DUOJIE_ANTHROPIC_MODELS

    def _get_api_url(self, provider: str, model: str = '') -> str:
        provider = (provider or 'openai').lower()
        if provider == 'deepseek':
            return self.DEEPSEEK_API_URL
        elif provider == 'glm':
            return self.GLM_API_URL
        elif provider == 'ollama':
            return self.OLLAMA_API_URL
        elif provider == 'duojie':
            if model and self._is_anthropic_protocol(provider, model):
                return self.DUOJIE_ANTHROPIC_API_URL
            return self.DUOJIE_API_URL
        elif provider == 'openrouter':
            return self.OPENROUTER_API_URL
        elif provider == 'anthropic':
            return self.ANTHROPIC_API_URL
        elif provider in self._EXTRA_PROVIDERS:
            return self._EXTRA_PROVIDERS[provider]['url']
        elif self._is_custom_provider(provider):
            url = (self._custom_cfg(provider).get('api_url') or '').strip()
            if not url:
                return self.OPENAI_API_URL
            # Accept either the full chat endpoint OR just the base URL
            # (e.g. "https://opencode.ai/zen/go/v1") — many providers'
            # own docs give you the base and expect the client to know to
            # append /chat/completions; without this, a base-only URL gets
            # POSTed to directly and 404s (often against an unrelated
            # marketing site route, not even the API subdomain's own 404).
            if not re.search(r'/(chat/)?completions/?$', url):
                url = url.rstrip('/') + '/chat/completions'
            return url
        return self.OPENAI_API_URL

    def _get_vendor_name(self, provider: str) -> str:
        names = {
            'openai': 'OpenAI', 'deepseek': 'DeepSeek',
            'glm': 'GLM (Zhipu AI)', 'ollama': 'Ollama',
            'duojie': 'Duojie', 'openrouter': 'OpenRouter',
            'anthropic': 'Anthropic', 'custom': 'Custom',
        }
        if provider in names:
            return names[provider]
        if provider in self._EXTRA_PROVIDERS:
            return self._EXTRA_PROVIDERS[provider]['name']
        return provider

    def set_custom_provider(self, api_url: str, api_key: str = '', supports_fc: bool = True):
        """Set runtime config for the Custom provider.

        Args:
            api_url: OpenAI-compatible API endpoint URL
            api_key: API key (may be empty)
            supports_fc: Whether the endpoint supports native Function Calling
        """
        self._CUSTOM_API_URL = api_url.strip()
        self._CUSTOM_SUPPORTS_FC = supports_fc
        if api_key:
            self._api_keys['custom'] = api_key.strip()

    # Curated per-family capability table (context tokens, vision, reasoning/
    # thinking, function-calling), checked in order — first substring match
    # wins, so put more specific patterns before their broader family.
    # Values are best-effort public knowledge (mirrors what models.dev
    # curates), not queried live — the /v1/models endpoint itself never
    # returns this metadata, so a name-pattern table is what LobeHub/OpenCode
    # fall back to as well for anything outside their built-in catalog.
    # (pattern, context, vision, reasoning, fc, input_$/M, output_$/M).
    # Pricing mirrors token_optimizer.MODEL_PRICING where a model overlaps;
    # same caveat as context/vision/reasoning — /v1/models never returns
    # pricing either, models.dev-style clients curate it by hand too.
    _FAMILY_CAPS = [
        ('claude-opus', 1000000, True, True, True, 15.00, 75.00),
        ('claude-sonnet', 1000000, True, True, True, 3.00, 15.00),
        ('claude-haiku', 200000, True, True, True, 0.80, 4.00),
        ('claude', 200000, True, True, True, 3.00, 15.00),
        ('gemini', 1048576, True, True, True, 1.25, 10.00),
        ('gpt-5', 400000, True, True, True, 2.50, 10.00),
        ('gpt-4o', 128000, True, False, True, 2.50, 10.00),
        ('gpt-4', 128000, True, False, True, 2.50, 10.00),
        ('o1', 200000, False, True, True, 15.00, 60.00),
        ('o3', 200000, False, True, True, 10.00, 40.00),
        ('o4', 200000, True, True, True, 1.10, 4.40),
        ('deepseek-v4-flash', 128000, False, True, True, 0.27, 1.10),
        ('deepseek-v4-pro', 128000, False, True, True, 0.55, 2.19),
        ('deepseek-v4', 128000, False, True, True, 0.27, 1.10),
        ('deepseek-r1', 64000, False, True, True, 0.55, 2.19),
        ('deepseek-reasoner', 64000, False, True, True, 0.55, 2.19),
        ('deepseek', 128000, False, False, True, 0.27, 1.10),
        ('glm-5', 200000, False, True, True, 0.50, 0.50),
        ('glm-4', 128000, False, True, True, 0.50, 0.50),
        ('glm', 128000, False, False, True, 0.50, 0.50),
        ('minimax-m', 512000, True, True, True, 1.00, 4.00),
        ('minimax', 256000, True, False, True, 1.00, 4.00),
        ('mimo', 1048576, True, True, True, 0.14, 0.28),
        ('kimi-k2', 262144, True, True, True, 2.00, 8.00),
        ('kimi', 200000, True, False, True, 2.00, 8.00),
        ('qwen3', 1048576, True, True, True, 0.80, 2.00),
        ('qwen2.5-vl', 128000, True, False, True, 0.80, 2.00),
        ('qwen', 131072, False, False, True, 0.80, 2.00),
        ('grok', 2000000, True, True, True, 5.00, 15.00),
        ('llama-4', 1048576, True, False, True, 0.20, 0.20),
        ('llama', 128000, False, False, True, 0.20, 0.20),
        ('mistral', 128000, False, False, True, 0.20, 0.60),
        ('pixtral', 128000, True, False, True, 0.20, 0.60),
        ('llava', 32000, True, False, False, 0.0, 0.0),
        ('internvl', 32000, True, False, False, 0.0, 0.0),
    ]

    @staticmethod
    def guess_model_capabilities(model_id: str) -> Dict[str, Any]:
        """Best-effort capability guess for a model discovered via /v1/models.

        The OpenAI-compatible /v1/models endpoint only ever returns
        {id, created, owned_by} — no context length, vision, reasoning,
        pricing, or function-calling metadata. Context/vision/reasoning are
        architectural properties of the model itself, so a name-pattern
        table transfers reasonably well regardless of which endpoint serves
        it (mirrors how models.dev curates a static catalog).

        Price is NOT guessed from that table, though — a reseller/aggregator
        endpoint (OpenRouter, "Open Agentic", OpenCode Zen, etc.) sets its
        own price for a model, often free or discounted vs. the vendor's
        published rate, so copying the vendor's real price here would
        actively show a WRONG, confidently-formatted number. Price is left
        unknown unless the id itself says otherwise (an explicit ":free" /
        "-free" tag, or an Ollama-style "name:tag" / GGUF-quant id that's
        almost always self-hosted).
        """
        m = (model_id or '').lower()
        is_free_tagged = bool(re.search(r'(^|[:\-_( ])free([)\-_ ]|$)', m))
        is_local = (
            ':' in m or any(k in m for k in ('gguf', 'ggml', '-q4', '-q5', '-q8', 'awq', 'exl2'))
        )
        price = {"inputPrice": None, "outputPrice": None, "priceEstimated": False}
        if is_free_tagged or is_local:
            price = {"inputPrice": 0.0, "outputPrice": 0.0, "priceEstimated": False}

        for pattern, context, vision, reasoning, fc, price_in, price_out in AIClient._FAMILY_CAPS:
            if pattern in m:
                row_price = price if (is_free_tagged or is_local) else {
                    # The vendor's real published price for this model family —
                    # shown as an ESTIMATE, not a fact, since a reseller can
                    # (and often does) charge something different.
                    "inputPrice": price_in, "outputPrice": price_out, "priceEstimated": True,
                }
                return {
                    "id": model_id, "contextLimit": context,
                    "supportsVision": vision, "supportsReasoning": reasoning, "supportsFc": fc,
                    **row_price,
                }
        small = bool(re.search(r'\b(1|2|3|4|7|8|9)b\b', m)) and not re.search(r'\b(70|72|90|235|405)b\b', m)
        return {
            "id": model_id,
            "contextLimit": 32000 if small else 128000,
            "supportsVision": False,
            "supportsReasoning": False,
            "supportsFc": not any(k in m for k in ('base', 'completion', 'instruct-raw', 'embed')),
            **price,
        }

    def get_custom_models(self, api_url: str = '', api_key: str = '', provider: str = 'custom') -> List[Dict[str, Any]]:
        """Auto-discover models on a Custom (OpenAI-compatible) endpoint via
        GET {base}/models — the standard OpenAI-compatible discovery route,
        same one LM Studio/vLLM/text-generation-webui expose. Mirrors
        get_ollama_models(); falls back to an empty list on any failure.
        Each result also carries a guessed capability set (see
        guess_model_capabilities) so the caller never needs manual input."""
        if not HAS_REQUESTS:
            return []
        base = (api_url or self._custom_cfg(provider).get('api_url') or '').strip()
        if not base:
            return []
        for suffix in ('/chat/completions', '/completions'):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        url = base.rstrip('/') + '/models'
        key = api_key or self._api_keys.get(provider, '')
        headers = {'Authorization': f'Bearer {key}'} if key else {}
        try:
            response = self._http_session.get(
                url, headers=headers, timeout=10,
                proxies={'http': None, 'https': None},
            )
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    ids = [m.get('id') for m in items if isinstance(m, dict) and m.get('id')]
                    return [self.guess_model_capabilities(i) for i in ids]
        except Exception:
            pass
        return []

    def get_builtin_models(self, provider: str) -> List[Dict[str, Any]]:
        """Live model list (with guessed capabilities) for an auto-fetch
        built-in provider. OpenAI-compatible ones reuse the standard
        GET /models discovery; Anthropic uses its own /v1/models. Returns []
        when the provider isn't fetchable or no key is set."""
        provider = (provider or '').lower()
        if provider == 'anthropic':
            return self._get_anthropic_models()
        if provider in self._EXTRA_PROVIDERS:
            key = self._get_api_key(provider)
            if not key:
                return []
            return self.get_custom_models(self._EXTRA_PROVIDERS[provider]['url'], key, provider)
        return []

    def _get_anthropic_models(self) -> List[Dict[str, Any]]:
        """Discover Claude models via Anthropic's native /v1/models
        (x-api-key + anthropic-version headers, not Bearer)."""
        if not HAS_REQUESTS:
            return []
        key = self._get_api_key('anthropic')
        if not key:
            return []
        headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
        try:
            response = self._http_session.get(
                self.ANTHROPIC_MODELS_URL, headers=headers, timeout=10,
                proxies={'http': None, 'https': None},
            )
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    ids = [m.get('id') for m in items if isinstance(m, dict) and m.get('id')]
                    return [self.guess_model_capabilities(i) for i in ids]
        except Exception:
            pass
        return []

    def set_ollama_url(self, base_url: str):
        """Set the Ollama service base URL."""
        self._ollama_base_url = base_url.rstrip('/')
        self.OLLAMA_API_URL = f"{self._ollama_base_url}/v1/chat/completions"

    def get_ollama_models(self) -> List[str]:
        """Get the list of models available on Ollama."""
        if not HAS_REQUESTS:
            return ['qwen2.5:14b']

        try:
            response = self._http_session.get(
                f"{self._ollama_base_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                models = [m.get('name', '') for m in data.get('models', [])]
                return models if models else ['qwen2.5:14b']
        except Exception:
            pass

        return ['qwen2.5:14b']  # Default model

    def test_connection(self, provider: str = 'deepseek') -> Dict[str, Any]:
        """Test the connection."""
        provider = (provider or 'deepseek').lower()

        # Ollama special-case
        if provider == 'ollama':
            try:
                if HAS_REQUESTS:
                    response = self._http_session.get(
                        f"{self._ollama_base_url}/api/tags",
                        timeout=5
                    )
                    if response.status_code == 200:
                        return {'ok': True, 'url': self._ollama_base_url, 'status': 200}
                    return {'ok': False, 'error': f'Ollama service returned unexpected status: {response.status_code}'}
            except Exception as e:
                return {'ok': False, 'error': f'Cannot reach Ollama service: {str(e)}'}

        api_key = self._get_api_key(provider)
        # Custom provider allows no API key (e.g. local services)
        if not api_key and not self._is_custom_provider(provider):
            return {'ok': False, 'error': 'Missing API key'}
        
        try:
            if HAS_REQUESTS:
                headers = {'Content-Type': 'application/json'}
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                response = self._http_session.post(
                    self._get_api_url(provider),
                    json={'model': self._get_default_model(provider), 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 1},
                    headers=headers,
                    timeout=15,
                    proxies={'http': None, 'https': None}
                )
                return {'ok': True, 'url': self._get_api_url(provider), 'status': response.status_code}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def _get_default_model(self, provider: str) -> str:
        defaults = {
            'openai': 'gpt-5.2', 
            'deepseek': 'deepseek-v4-flash',
            'glm': 'glm-4.7',
            'ollama': 'qwen2.5:14b',
            'openrouter': 'anthropic/claude-sonnet-4.6',
        }
        return defaults.get(provider, 'gpt-5.2')

    # ============================================================
    # Model capability checks
    # ============================================================

    @staticmethod
    def is_reasoning_model(model: str) -> bool:
        """Check whether the model is a native reasoning model (API returns reasoning_content).

        Limited to models that explicitly return reasoning via the reasoning_content field:
        DeepSeek V4 (flash/pro), DeepSeek-R1/Reasoner, GLM-4.7.
        Note: Duojie models implement thinking mode via <think> tags in the system prompt,
        not via API params.
        """
        m = model.lower()
        return (
            'deepseek-v4' in m
            or 'reasoner' in m or 'r1' in m
            or m == 'glm-4.7'
        )

    @staticmethod
    def is_glm47(model: str) -> bool:
        """Return whether the model is GLM-4.7."""
        return model.lower() == 'glm-4.7'

    # Duojie thinking mode notes:
    # Testing showed thinking/reasoningEffort API params have no effect on Duojie (reasoning_tokens always 0)
    # Thinking is driven by <think> tags in the system prompt; the model name stays the same.

    # ============================================================
    # Usage parsing
    # ============================================================

    _usage_keys_logged = False  # Class var: only log the raw usage structure once

    @staticmethod
    def _parse_usage(usage: dict) -> dict:
        """Parse the usage payload returned by the API into a uniform shape
        (includes reasoning tokens and cache metrics).

        Cache fields cover multiple API response formats:
        - DeepSeek/OpenAI: prompt_cache_hit_tokens / prompt_cache_miss_tokens
        - Anthropic native: cache_read_input_tokens / cache_creation_input_tokens
        - Factory/Duojie proxy: claude_cache_creation_*_tokens, nested in input_tokens_details
        """
        if not usage:
            return {}

        # Diagnostic: log the full structure (including nested details) the first time
        if not AIClient._usage_keys_logged:
            AIClient._usage_keys_logged = True
            _dbg(f"[AI Client] Raw usage keys (first): {sorted(usage.keys())}")
            for k in ('input_tokens_details', 'prompt_tokens_details', 'completion_tokens_details'):
                v = usage.get(k)
                if v:
                    _dbg(f"[AI Client]   {k}: {v}")

        prompt_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)

        # -- Cache read (hit): look across multiple sources --
        # Prefer details sub-fields (Factory/Anthropic style)
        input_details = usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}
        if isinstance(input_details, dict):
            cache_hit = (
                input_details.get('cached_tokens')           # OpenAI new format
                or input_details.get('cache_read_input_tokens')  # Anthropic
                or input_details.get('cache_read_tokens')
                or 0
            )
        else:
            cache_hit = 0
        # Fall back to top-level fields
        if not cache_hit:
            cache_hit = (
                usage.get('prompt_cache_hit_tokens')
                or usage.get('cache_read_input_tokens')
                or usage.get('cache_read_tokens')
                or usage.get('cache_hit_tokens')
                or 0
            )

        # -- Cache write (miss/creation) --
        # Factory-specific: claude_cache_creation_1_h_tokens / claude_cache_creation_5_m_tokens
        cache_write_1h = usage.get('claude_cache_creation_1_h_tokens', 0) or 0
        cache_write_5m = usage.get('claude_cache_creation_5_m_tokens', 0) or 0
        factory_cache_write = cache_write_1h + cache_write_5m

        if isinstance(input_details, dict):
            cache_miss_from_details = (
                input_details.get('cache_creation_input_tokens')
                or input_details.get('cache_creation_tokens')
                or 0
            )
        else:
            cache_miss_from_details = 0

        cache_miss = (
            cache_miss_from_details
            or usage.get('prompt_cache_miss_tokens')
            or usage.get('cache_creation_input_tokens')
            or usage.get('cache_write_tokens')
            or usage.get('cache_miss_tokens')
            or factory_cache_write
            or 0
        )

        completion = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
        total = usage.get('total_tokens', 0) or (prompt_tokens + completion)

        # -- Extract reasoning / thinking tokens --
        # OpenAI/DeepSeek: completion_tokens_details.reasoning_tokens
        # Anthropic: may live in output_tokens_details.thinking
        reasoning_tokens = 0
        comp_details = usage.get('completion_tokens_details') or {}
        if isinstance(comp_details, dict):
            reasoning_tokens = comp_details.get('reasoning_tokens', 0) or 0
        if not reasoning_tokens:
            reasoning_tokens = usage.get('reasoning_tokens', 0) or 0
        
        return {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion,
            'reasoning_tokens': reasoning_tokens,
            'total_tokens': total,
            'cache_hit_tokens': cache_hit,
            'cache_miss_tokens': cache_miss,
            'cache_hit_rate': (cache_hit / prompt_tokens) if prompt_tokens > 0 else 0,
        }
    
    # ============================================================
    # Anthropic Messages protocol adapter
    # ============================================================

    @staticmethod
    def _convert_messages_to_anthropic(messages: List[Dict[str, Any]]) -> tuple:
        """Convert an OpenAI-format message list to Anthropic Messages API format.

        Returns:
            (system_text, anthropic_messages)
            - system_text: system prompt (Anthropic takes this as a separate `system` parameter)
            - anthropic_messages: messages list in Anthropic format
        """
        system_text = ""
        anthropic_msgs: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get('role', '')

            if role == 'system':
                # Anthropic's system isn't in messages; passed separately
                system_text += (("\n\n" if system_text else "") + (msg.get('content', '') or ''))
                continue

            if role == 'user':
                content = msg.get('content', '')
                # Support OpenAI multimodal format: content may be a list
                if isinstance(content, list):
                    # Convert OpenAI multimodal -> Anthropic format
                    anth_content = []
                    for part in content:
                        if part.get('type') == 'text':
                            anth_content.append({'type': 'text', 'text': part['text']})
                        elif part.get('type') == 'image_url':
                            url = part.get('image_url', {}).get('url', '')
                            if url.startswith('data:'):
                                # data:image/png;base64,xxxx
                                import re as _re
                                m = _re.match(r'data:(image/\w+);base64,(.+)', url, _re.DOTALL)
                                if m:
                                    anth_content.append({
                                        'type': 'image',
                                        'source': {
                                            'type': 'base64',
                                            'media_type': m.group(1),
                                            'data': m.group(2),
                                        }
                                    })
                            else:
                                anth_content.append({
                                    'type': 'image',
                                    'source': {'type': 'url', 'url': url}
                                })
                    anthropic_msgs.append({'role': 'user', 'content': anth_content})
                else:
                    anthropic_msgs.append({'role': 'user', 'content': str(content or '')})
                continue
            
            if role == 'assistant':
                content_blocks: List[Dict[str, Any]] = []
                text = msg.get('content')
                if text:
                    content_blocks.append({'type': 'text', 'text': str(text)})
                # tool_calls → tool_use blocks
                for tc in (msg.get('tool_calls') or []):
                    func = tc.get('function', {})
                    try:
                        input_obj = json.loads(func.get('arguments', '{}'))
                    except (json.JSONDecodeError, ValueError):
                        input_obj = {}
                    content_blocks.append({
                        'type': 'tool_use',
                        'id': tc.get('id', ''),
                        'name': func.get('name', ''),
                        'input': input_obj,
                    })
                if not content_blocks:
                    content_blocks.append({'type': 'text', 'text': ''})
                anthropic_msgs.append({'role': 'assistant', 'content': content_blocks})
                continue
            
            if role == 'tool':
                # OpenAI tool result -> Anthropic tool_result (lives inside a user message)
                tool_result_block = {
                    'type': 'tool_result',
                    'tool_use_id': msg.get('tool_call_id', ''),
                    'content': str(msg.get('content', '')),
                }
                # If the previous entry is also a user (consecutive tool results), merge into the same user message
                if anthropic_msgs and anthropic_msgs[-1]['role'] == 'user':
                    last_content = anthropic_msgs[-1]['content']
                    if isinstance(last_content, list):
                        last_content.append(tool_result_block)
                    else:
                        anthropic_msgs[-1]['content'] = [
                            {'type': 'text', 'text': last_content},
                            tool_result_block,
                        ]
                else:
                    anthropic_msgs.append({
                        'role': 'user',
                        'content': [tool_result_block],
                    })
                continue

        # Anthropic requires messages start with user; if the first is assistant, prepend a user
        if anthropic_msgs and anthropic_msgs[0]['role'] == 'assistant':
            anthropic_msgs.insert(0, {'role': 'user', 'content': 'Please continue.'})

        # Anthropic requires roles strictly alternate (user/assistant/user/...)
        # Merge consecutive same-role messages
        merged: List[Dict[str, Any]] = []
        for m in anthropic_msgs:
            if merged and merged[-1]['role'] == m['role']:
                # Merge content
                prev_content = merged[-1]['content']
                curr_content = m['content']
                # Normalize to list format
                if isinstance(prev_content, str):
                    prev_content = [{'type': 'text', 'text': prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{'type': 'text', 'text': curr_content}]
                if not isinstance(prev_content, list):
                    prev_content = [prev_content]
                if not isinstance(curr_content, list):
                    curr_content = [curr_content]
                merged[-1]['content'] = prev_content + curr_content
            else:
                merged.append(m)
        
        return system_text, merged

    @staticmethod
    def _convert_tools_to_anthropic(tools: List[dict]) -> List[dict]:
        """Convert an OpenAI Function Calling tool list to Anthropic format.

        OpenAI:  {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
        Anthropic: {"name": ..., "description": ..., "input_schema": {...}}
        """
        if not tools:
            return []
        anthropic_tools = []
        for tool in tools:
            func = tool.get('function', tool)  # Tolerate a bare function dict
            anthropic_tools.append({
                'name': func.get('name', ''),
                'description': func.get('description', ''),
                'input_schema': func.get('parameters', {'type': 'object', 'properties': {}}),
            })
        return anthropic_tools

    def _chat_stream_anthropic(self,
                                messages: List[Dict[str, Any]],
                                model: str,
                                provider: str,
                                temperature: float = 0.17,
                                max_tokens: Optional[int] = None,
                                tools: Optional[List[dict]] = None,
                                tool_choice: str = 'auto',
                                enable_thinking: bool = True,
                                reasoning_effort: Optional[str] = None,
                                api_key: str = '') -> Generator[Dict[str, Any], None, None]:
        """Streaming Chat over the Anthropic Messages protocol.

        Converts OpenAI-format input to Anthropic format, calls /v1/messages,
        parses the Anthropic SSE event stream, and yields the same internal chunk
        format as the OpenAI branch.
        """
        api_url = self._get_api_url(provider, model)

        # Message conversion
        system_text, anth_messages = self._convert_messages_to_anthropic(messages)

        payload: Dict[str, Any] = {
            'model': model,
            'messages': anth_messages,
            'max_tokens': max_tokens or 16384,
            'stream': True,
        }
        # temperature (Anthropic range 0-1)
        if temperature is not None:
            payload['temperature'] = min(max(temperature, 0.0), 1.0)

        if system_text:
            payload['system'] = system_text

        # Thinking mode — budget_tokens scales with the requested reasoning effort
        if enable_thinking:
            budget = BUDGET_TOKENS_BY_LEVEL.get((reasoning_effort or 'medium').lower(), 6000)
            payload['thinking'] = {'type': 'enabled', 'budget_tokens': min(max_tokens or 16384, budget)}

        # Tools
        if tools:
            payload['tools'] = self._convert_tools_to_anthropic(tools)
            if tool_choice == 'auto':
                payload['tool_choice'] = {'type': 'auto'}
            elif tool_choice == 'none':
                payload['tool_choice'] = {'type': 'none'}
            elif tool_choice == 'required':
                payload['tool_choice'] = {'type': 'any'}

        # Request headers (Anthropic format)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
        
        _dbg(f"[AI Client] Anthropic protocol: {api_url} model={model}")
        
        for attempt in range(self._max_retries):
            try:
                with self._http_session.post(
                    api_url,
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=(10, self._chunk_timeout),
                    proxies={'http': None, 'https': None}
                ) as response:
                    response.encoding = 'utf-8'
                    _dbg(f"[AI Client] Anthropic response status: {response.status_code}")
                    
                    if response.status_code != 200:
                        try:
                            err = response.json()
                            err_msg = err.get('error', {}).get('message', response.text)
                        except Exception:
                            err_msg = response.text
                        _dbg(f"[AI Client] Anthropic error: {err_msg}")
                        
                        if response.status_code >= 500 and attempt < self._max_retries - 1:
                            wait = self._retry_delay * (attempt + 1)
                            _dbg(f"[AI Client] Anthropic server error {response.status_code}, retrying in {wait}s...")
                            time.sleep(wait)
                            continue
                        
                        yield {"type": "error", "error": f"HTTP {response.status_code}: {err_msg}"}
                        return
                    
                    # -- Parse the Anthropic SSE event stream --
                    # State
                    _content_blocks: Dict[int, Dict[str, Any]] = {}  # index -> block info
                    _tool_args_acc: Dict[int, str] = {}  # index -> accumulated JSON args
                    _pending_usage: Dict[str, Any] = {}
                    _last_stop_reason = None
                    _got_thinking = False
                    _enable_thinking_flag = enable_thinking  # Closure var

                    import codecs
                    _utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
                    _line_buf = ""
                    _event_type = ""  # Current SSE event type

                    def _process_anthropic_event(event_type: str, data_str: str):
                        """Process a single Anthropic SSE event; return the list of dicts to yield."""
                        nonlocal _content_blocks, _tool_args_acc, _pending_usage, _last_stop_reason, _got_thinking
                        results = []
                        
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            return results
                        
                        ev_type = data.get('type', event_type)
                        
                        if ev_type == 'message_start':
                            msg = data.get('message', {})
                            usage = msg.get('usage', {})
                            if usage:
                                _pending_usage = self._parse_usage(usage)
                        
                        elif ev_type == 'content_block_start':
                            idx = data.get('index', 0)
                            block = data.get('content_block', {})
                            _content_blocks[idx] = {
                                'type': block.get('type', 'text'),
                                'id': block.get('id', ''),
                                'name': block.get('name', ''),
                            }
                            if block.get('type') == 'tool_use':
                                _tool_args_acc[idx] = ''
                        
                        elif ev_type == 'content_block_delta':
                            idx = data.get('index', 0)
                            delta = data.get('delta', {})
                            delta_type = delta.get('type', '')
                            block_info = _content_blocks.get(idx, {})
                            
                            if delta_type == 'text_delta':
                                text = delta.get('text', '')
                                if text:
                                    results.append({"type": "content", "content": text})
                            
                            elif delta_type == 'thinking_delta':
                                thinking = delta.get('thinking', '')
                                if thinking:
                                    if not _got_thinking:
                                        _got_thinking = True
                                        _dbg(f"[AI Client] 🧠 Anthropic thinking (first chunk, len={len(thinking)}, enable={_enable_thinking_flag})")
                                    if _enable_thinking_flag:
                                        results.append({"type": "thinking", "content": thinking})
                            
                            elif delta_type == 'input_json_delta':
                                partial = delta.get('partial_json', '')
                                if partial and idx in _tool_args_acc:
                                    _tool_args_acc[idx] += partial
                                    # Emit tool_args_delta -> UI streaming preview
                                    tool_name = block_info.get('name', '')
                                    if tool_name:
                                        results.append({
                                            "type": "tool_args_delta",
                                            "index": idx,
                                            "name": tool_name,
                                            "delta": partial,
                                            "accumulated": _tool_args_acc[idx],
                                        })
                        
                        elif ev_type == 'content_block_stop':
                            idx = data.get('index', 0)
                            block_info = _content_blocks.get(idx, {})
                            if block_info.get('type') == 'tool_use':
                                # Tool call complete -> convert to OpenAI-format tool_call
                                tool_id = block_info.get('id', '')
                                tool_name = block_info.get('name', '')
                                args_str = _tool_args_acc.get(idx, '{}')
                                results.append({
                                    "type": "tool_call",
                                    "tool_call": {
                                        'id': tool_id,
                                        'type': 'function',
                                        'function': {
                                            'name': tool_name,
                                            'arguments': args_str,
                                        }
                                    }
                                })
                        
                        elif ev_type == 'message_delta':
                            delta = data.get('delta', {})
                            _last_stop_reason = delta.get('stop_reason')
                            usage = data.get('usage', {})
                            if usage:
                                # Merge usage
                                parsed = self._parse_usage(usage)
                                for k, v in parsed.items():
                                    if isinstance(v, (int, float)):
                                        _pending_usage[k] = _pending_usage.get(k, 0) + v

                        elif ev_type == 'message_stop':
                            # Map stop_reason: end_turn -> stop, tool_use -> tool_calls
                            finish = 'stop'
                            if _last_stop_reason == 'tool_use':
                                finish = 'tool_calls'
                            elif _last_stop_reason == 'max_tokens':
                                finish = 'length'
                            results.append({
                                "type": "done",
                                "finish_reason": finish,
                                "usage": _pending_usage,
                            })
                        
                        elif ev_type == 'error':
                            err_msg = data.get('error', {}).get('message', str(data))
                            results.append({"type": "error", "error": err_msg})
                        
                        return results
                    
                    # -- Main loop --
                    _should_return = False
                    for raw_chunk in response.iter_content(chunk_size=4096, decode_unicode=False):
                        if not raw_chunk:
                            continue
                        if self._stop_event.is_set():
                            yield {"type": "stopped", "message": "User stopped the request"}
                            return

                        decoded = _utf8_decoder.decode(raw_chunk)
                        _line_buf += decoded

                        while '\n' in _line_buf:
                            one_line, _line_buf = _line_buf.split('\n', 1)
                            one_line = one_line.rstrip('\r')

                            if not one_line:
                                continue

                            # Anthropic SSE: "event: xxx" line followed by "data: {...}" line
                            if one_line.startswith('event: '):
                                _event_type = one_line[7:].strip()
                                continue

                            if one_line.startswith('data: '):
                                data_str = one_line[6:]
                                for item in _process_anthropic_event(_event_type, data_str):
                                    yield item
                                    if item.get('type') in ('done', 'error'):
                                        _should_return = True
                                _event_type = ""  # Reset

                        if _should_return:
                            return

                    # Flush leftover
                    _line_buf += _utf8_decoder.decode(b'', final=True)
                    if _line_buf.strip():
                        for line in _line_buf.strip().split('\n'):
                            line = line.strip()
                            if line.startswith('event: '):
                                _event_type = line[7:].strip()
                            elif line.startswith('data: '):
                                for item in _process_anthropic_event(_event_type, line[6:]):
                                    yield item
                                    if item.get('type') in ('done', 'error'):
                                        return

                    # Stream ended without a message_stop
                    if not _should_return:
                        yield {"type": "done", "finish_reason": _last_stop_reason or "stop", "usage": _pending_usage}
                    return

            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                yield {"type": "error", "error": f"Request timed out (retried {self._max_retries} times)"}
                return
            except requests.exceptions.ConnectionError as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                yield {"type": "error", "error": f"Connection error: {str(e)}"}
                return
            except Exception as e:
                err_str = str(e)
                is_transient = any(k in err_str for k in (
                    'InvalidChunkLength', 'ChunkedEncodingError',
                    'Connection broken', 'IncompleteRead',
                    'ConnectionReset', 'RemoteDisconnected',
                ))
                if is_transient and attempt < self._max_retries - 1:
                    wait = self._retry_delay * (attempt + 1)
                    _dbg(f"[AI Client] Anthropic connection interrupted ({err_str[:80]}), retrying in {wait}s")
                    time.sleep(wait)
                    continue
                yield {"type": "error", "error": f"Request failed: {err_str}"}
                return

    def _chat_anthropic(self,
                        messages: List[Dict[str, Any]],
                        model: str,
                        provider: str,
                        temperature: float = 0.17,
                        max_tokens: int = 4096,
                        tools: Optional[List[dict]] = None,
                        tool_choice: str = 'auto',
                        api_key: str = '',
                        timeout: int = 60) -> Dict[str, Any]:
        """Non-streaming Chat over the Anthropic Messages protocol."""
        api_url = self._get_api_url(provider, model)
        system_text, anth_messages = self._convert_messages_to_anthropic(messages)
        
        payload: Dict[str, Any] = {
            'model': model,
            'messages': anth_messages,
            'max_tokens': max_tokens,
        }
        if temperature is not None:
            payload['temperature'] = min(max(temperature, 0.0), 1.0)
        if system_text:
            payload['system'] = system_text
        if tools:
            payload['tools'] = self._convert_tools_to_anthropic(tools)
            if tool_choice == 'auto':
                payload['tool_choice'] = {'type': 'auto'}
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
        
        for attempt in range(self._max_retries):
            try:
                response = self._http_session.post(
                    api_url, json=payload, headers=headers,
                    timeout=timeout, proxies={'http': None, 'https': None}
                )
                response.raise_for_status()
                obj = response.json()

                # Parse Anthropic response -> unified OpenAI shape
                content_text = ''
                tool_calls_list = []
                for block in obj.get('content', []):
                    if block.get('type') == 'text':
                        content_text += block.get('text', '')
                    elif block.get('type') == 'tool_use':
                        tool_calls_list.append({
                            'id': block.get('id', ''),
                            'type': 'function',
                            'function': {
                                'name': block.get('name', ''),
                                'arguments': json.dumps(block.get('input', {}), ensure_ascii=False),
                            }
                        })
                
                stop_reason = obj.get('stop_reason', 'end_turn')
                finish = 'stop' if stop_reason == 'end_turn' else ('tool_calls' if stop_reason == 'tool_use' else stop_reason)
                
                return {
                    'ok': True,
                    'content': content_text or None,
                    'tool_calls': tool_calls_list or None,
                    'finish_reason': finish,
                    'usage': self._parse_usage(obj.get('usage', {})),
                    'raw': obj,
                }
            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                return {'ok': False, 'error': 'Request timed out'}
            except Exception as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                return {'ok': False, 'error': str(e)}

        return {'ok': False, 'error': 'Request failed'}

    # ============================================================
    # Streaming Chat
    # ============================================================

    def chat_stream(self,
                    messages: List[Dict[str, str]],
                    model: str = 'gpt-5.2',
                    provider: str = 'openai',
                    temperature: float = 0.17,
                    max_tokens: Optional[int] = None,
                    tools: Optional[List[dict]] = None,
                    tool_choice: str = 'auto',
                    enable_thinking: bool = True,
                    reasoning_effort: Optional[str] = None,
                    response_format: Optional[dict] = None) -> Generator[Dict[str, Any], None, None]:
        """Streaming Chat API.

        Yields:
            {"type": "content", "content": str}  # Content fragment
            {"type": "tool_call", "tool_call": dict}  # Tool call
            {"type": "thinking", "content": str}  # Thinking content (DeepSeek / GLM native reasoning_content)
            {"type": "done", "finish_reason": str}  # Completion
            {"type": "error", "error": str}  # Error
        """
        if not HAS_REQUESTS:
            yield {"type": "error", "error": "The 'requests' library must be installed"}
            return

        provider = (provider or 'openai').lower()
        api_key = self._get_api_key(provider)

        # Ollama / Custom (no key) don't require API key validation
        if provider != 'ollama' and not self._is_custom_provider(provider) and not api_key:
            yield {"type": "error", "error": f"Missing {self._get_vendor_name(provider)} API key"}
            return

        # ★ Anthropic protocol branch (Duojie GLM etc.)
        if self._is_anthropic_protocol(provider, model):
            yield from self._chat_stream_anthropic(
                messages=messages, model=model, provider=provider,
                temperature=temperature, max_tokens=max_tokens,
                tools=tools, tool_choice=tool_choice,
                enable_thinking=enable_thinking, reasoning_effort=reasoning_effort,
                api_key=api_key,
            )
            return

        api_url = self._get_api_url(provider, model)

        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'stream': True,
            # stream_options is required to receive usage stats in a streaming response
            'stream_options': {'include_usage': True},
        }
        # Always cap output. If omitted, providers (esp. OpenRouter/Anthropic) default to
        # the model's FULL max output (e.g. 65536 for Opus), which inflates cost AND trips
        # OpenRouter's affordability pre-check (HTTP 402). 16384 is ample for one agent step.
        payload['max_tokens'] = max_tokens if max_tokens else 16384
        if response_format:
            payload['response_format'] = response_format

        # GLM-4.7 specific params (only on the native GLM endpoint): deep thinking + streaming tool calls
        if self.is_glm47(model) and provider == 'glm' and enable_thinking:
            payload['thinking'] = {'type': 'enabled'}
            if tools:
                payload['tool_stream'] = True

        # DeepSeek V4 thinking params (v4-flash / v4-pro enable thinking explicitly)
        if provider == 'deepseek' and enable_thinking and 'deepseek-v4' in model.lower():
            payload['thinking'] = {'type': 'enabled'}
            if 'v4-pro' in model.lower():
                payload['reasoning_effort'] = (reasoning_effort or 'high')

        # OpenAI o-series / gpt-5.x reasoning models: real low/medium/high effort control
        if enable_thinking and reasoning_effort and get_reasoning_capability(model, provider)['kind'] == 'effort':
            payload['reasoning_effort'] = reasoning_effort

        # Duojie proxy: thinking mode is implemented via <think> tags in the system prompt
        # Testing showed thinking/reasoningEffort params have no effect on Duojie API (reasoning_tokens always 0)
        # The thinking param also occasionally triggers 403, so we don't send any extra params

        # DeepSeek / OpenAI prompt caching is enabled automatically (keep the prefix stable to hit)

        # Tool calls (universal across providers that support function calling)
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice

        # Build request headers
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        }

        # Ollama and key-less Custom don't need an Authorization header
        if provider != 'ollama' and api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        # OpenRouter requires extra headers to identify the caller (see https://openrouter.ai/docs/quickstart)
        if provider == 'openrouter':
            headers['HTTP-Referer'] = 'https://github.com/Kazama-Suichiku/Houdini-Agent'
            headers['X-OpenRouter-Title'] = 'MorfyAI - Houdini Assistant'

        # Retry loop
        _dbg(f"[AI Client] Requesting {api_url} with model {model}")
        for attempt in range(self._max_retries):
            try:
                with self._http_session.post(
                    api_url,
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=(10, self._chunk_timeout),  # (connect timeout, read timeout)
                    proxies={'http': None, 'https': None}
                ) as response:
                    # Force UTF-8 (requests defaults text/event-stream to ISO-8859-1, mangling CJK)
                    response.encoding = 'utf-8'
                    _dbg(f"[AI Client] Response status: {response.status_code}")

                    if response.status_code != 200:
                        try:
                            err = response.json()
                            err_msg = err.get('error', {}).get('message', response.text)
                        except:
                            err_msg = response.text
                        _dbg(f"[AI Client] Error: {err_msg}")

                        # 5xx server errors (502/503/529 etc.) are retryable
                        if response.status_code >= 500 and attempt < self._max_retries - 1:
                            wait = self._retry_delay * (attempt + 1)
                            _dbg(f"[AI Client] Server error {response.status_code}, retrying in {wait}s...")
                            time.sleep(wait)
                            continue  # Retry

                        yield {"type": "error", "error": f"HTTP {response.status_code}: {err_msg}"}
                        return

                    # Parse the SSE stream
                    tool_calls_buffer = {}  # Buffer tool call fragments
                    pending_usage = {}  # Collect usage data
                    last_finish_reason = None
                    _got_reasoning = False  # Diagnostic: did we receive reasoning_content this turn?
                    _enable_thinking = enable_thinking  # Closure var for _process_sse_line

                    # -- Use iter_content + incremental decoder + manual line splitting --
                    # More robust than iter_lines():
                    #   1. iter_content() returns raw byte chunks from the HTTP body
                    #   2. Incremental decoder correctly handles multibyte UTF-8 split across chunks
                    #   3. Manual \n splitting avoids requests' internal line-splitting encoding quirks
                    import codecs
                    _utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
                    _line_buf = ""  # Decoded text awaiting a \n

                    def _process_sse_line(line):
                        """Process a single SSE data line; return the list of dicts to yield."""
                        nonlocal tool_calls_buffer, pending_usage, last_finish_reason, _got_reasoning, _enable_thinking
                        results = []

                        if not line.startswith('data: '):
                            return results

                        data_str = line[6:]

                        if data_str.strip() == '[DONE]':
                            _reason_tokens = pending_usage.get('reasoning_tokens', 0)
                            _dbg(f"[AI Client] Received [DONE], reasoning={'YES' if _got_reasoning else 'NO'}(tokens={_reason_tokens}), usage={pending_usage}")
                            results.append({"type": "done", "finish_reason": last_finish_reason or "stop", "usage": pending_usage})
                            return results

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            return results

                        choices = data.get('choices', [])
                        usage_data = data.get('usage')

                        # usage-only chunk
                        if usage_data:
                            pending_usage = self._parse_usage(usage_data)

                        if not choices:
                            return results

                        choice = choices[0]
                        delta = choice.get('delta', {})
                        finish_reason = choice.get('finish_reason')

                        # Thinking content (only shown when enable_thinking=True)
                        # Different proxies use different field names: reasoning_content / thinking_content / reasoning
                        # Intercept all of them; when Think is off, silently drop
                        _thinking_text = (
                            delta.get('reasoning_content')
                            or delta.get('thinking_content')
                            or delta.get('reasoning')
                            or ''
                        )
                        if _thinking_text:
                            if not _got_reasoning:
                                _got_reasoning = True
                                # Diagnostic: log the field name for debugging
                                _field = ('reasoning_content' if 'reasoning_content' in delta
                                          else 'thinking_content' if 'thinking_content' in delta
                                          else 'reasoning')
                                _dbg(f"[AI Client] Received {_field} (first chunk, len={len(_thinking_text)}, enable_thinking={_enable_thinking})")
                            if _enable_thinking:
                                results.append({"type": "thinking", "content": _thinking_text})

                        # Normal content
                        if 'content' in delta and delta['content']:
                            results.append({"type": "content", "content": delta['content']})

                        # Tool calls
                        if delta.get('tool_calls'):
                            for tc in delta['tool_calls']:
                                idx = tc.get('index', 0)
                                tc_id = tc.get('id', '')
                                
                                if tc_id and idx in tool_calls_buffer:
                                    existing_id = tool_calls_buffer[idx].get('id', '')
                                    if existing_id and existing_id != tc_id:
                                        idx = max(tool_calls_buffer.keys()) + 1
                                
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        'id': tc_id,
                                        'type': 'function',
                                        'function': {'name': '', 'arguments': ''}
                                    }
                                
                                if tc_id:
                                    tool_calls_buffer[idx]['id'] = tc_id
                                if 'function' in tc:
                                    fn = tc['function']
                                    if 'name' in fn and fn['name']:
                                        tool_calls_buffer[idx]['function']['name'] = fn['name']
                                    if 'arguments' in fn:
                                        tool_calls_buffer[idx]['function']['arguments'] += fn['arguments']
                                        # ★ Emit tool_call arg deltas -> UI streaming preview
                                        _tname = tool_calls_buffer[idx]['function'].get('name', '')
                                        if _tname:
                                            results.append({
                                                "type": "tool_args_delta",
                                                "index": idx,
                                                "name": _tname,
                                                "delta": fn['arguments'],
                                                "accumulated": tool_calls_buffer[idx]['function']['arguments'],
                                            })
                        
                        # Completion (emit tool calls first, don't return; wait for the trailing usage chunk / [DONE])
                        if finish_reason:
                            if tool_calls_buffer:
                                # ★ Fix: detect and split arguments that the proxy concatenated by mistake (e.g. duojie Claude proxy)
                                # Some proxies use the same index for multiple tool calls while streaming, resulting in {...}{...}
                                import uuid as _uuid
                                fixed_buffer = {}
                                next_fix_idx = max(tool_calls_buffer.keys()) + 1
                                for idx_k in sorted(tool_calls_buffer.keys()):
                                    tc_entry = tool_calls_buffer[idx_k]
                                    args_str = tc_entry['function']['arguments'].strip()
                                    if args_str.startswith('{'):
                                        try:
                                            json.loads(args_str)
                                            fixed_buffer[idx_k] = tc_entry
                                        except (json.JSONDecodeError, ValueError):
                                            # Try to split into multiple concatenated JSON objects: {...}{...}
                                            split_parts = []
                                            depth = 0
                                            start = -1
                                            for ci, ch in enumerate(args_str):
                                                if ch == '{':
                                                    if depth == 0:
                                                        start = ci
                                                    depth += 1
                                                elif ch == '}':
                                                    depth -= 1
                                                    if depth == 0 and start >= 0:
                                                        part = args_str[start:ci+1]
                                                        try:
                                                            json.loads(part)
                                                            split_parts.append(part)
                                                        except:
                                                            pass
                                                        start = -1
                                            if split_parts:
                                                _dbg(f"[AI Client] Fixed concatenated tool_call arguments: split into {len(split_parts)} independent call(s)")
                                                tc_entry['function']['arguments'] = split_parts[0]
                                                fixed_buffer[idx_k] = tc_entry
                                                for extra_args in split_parts[1:]:
                                                    fixed_buffer[next_fix_idx] = {
                                                        'id': f"call_{_uuid.uuid4().hex[:24]}",
                                                        'type': 'function',
                                                        'function': {
                                                            'name': tc_entry['function']['name'],
                                                            'arguments': extra_args
                                                        }
                                                    }
                                                    next_fix_idx += 1
                                            else:
                                                fixed_buffer[idx_k] = tc_entry
                                    else:
                                        fixed_buffer[idx_k] = tc_entry
                                tool_calls_buffer = fixed_buffer

                                for idx_k in sorted(tool_calls_buffer.keys()):
                                    results.append({"type": "tool_call", "tool_call": tool_calls_buffer[idx_k]})
                                tool_calls_buffer = {}
                            last_finish_reason = finish_reason
                        
                        return results
                    
                    # -- Main loop: read raw byte chunks -> decode -> split lines -> process --
                    _should_return = False
                    for raw_chunk in response.iter_content(chunk_size=4096, decode_unicode=False):
                        if not raw_chunk:
                            continue

                        if self._stop_event.is_set():
                            yield {"type": "stopped", "message": "User stopped the request"}
                            return

                        # Incremental decode: multibyte UTF-8 chars split across chunks reassemble here
                        decoded = _utf8_decoder.decode(raw_chunk)
                        _line_buf += decoded

                        # Split by line and process
                        while '\n' in _line_buf:
                            one_line, _line_buf = _line_buf.split('\n', 1)
                            one_line = one_line.rstrip('\r')
                            if not one_line:
                                continue

                            for item in _process_sse_line(one_line):
                                yield item
                                if item.get('type') == 'done':
                                    _should_return = True

                        if _should_return:
                            return

                    # Flush trailing buffer (stream ended without a \n-terminated final line)
                    _line_buf += _utf8_decoder.decode(b'', final=True)
                    if _line_buf.strip():
                        for item in _process_sse_line(_line_buf.strip()):
                            yield item
                            if item.get('type') == 'done':
                                return

                    # Stream ended without [DONE]
                    if tool_calls_buffer:
                        # ★ Also fix concatenated arguments (consistent with the finish_reason branch)
                        import uuid as _uuid2
                        fixed_buffer2 = {}
                        next_fix_idx2 = max(tool_calls_buffer.keys()) + 1
                        for idx_k2 in sorted(tool_calls_buffer.keys()):
                            tc_entry2 = tool_calls_buffer[idx_k2]
                            args_str2 = tc_entry2['function']['arguments'].strip()
                            if args_str2.startswith('{'):
                                try:
                                    json.loads(args_str2)
                                    fixed_buffer2[idx_k2] = tc_entry2
                                except (json.JSONDecodeError, ValueError):
                                    split_parts2 = []
                                    depth2 = 0
                                    start2 = -1
                                    for ci2, ch2 in enumerate(args_str2):
                                        if ch2 == '{':
                                            if depth2 == 0:
                                                start2 = ci2
                                            depth2 += 1
                                        elif ch2 == '}':
                                            depth2 -= 1
                                            if depth2 == 0 and start2 >= 0:
                                                part2 = args_str2[start2:ci2+1]
                                                try:
                                                    json.loads(part2)
                                                    split_parts2.append(part2)
                                                except:
                                                    pass
                                                start2 = -1
                                    if split_parts2:
                                        _dbg(f"[AI Client] Fixed concatenated tool_call arguments (tail): split into {len(split_parts2)} independent call(s)")
                                        tc_entry2['function']['arguments'] = split_parts2[0]
                                        fixed_buffer2[idx_k2] = tc_entry2
                                        for extra_args2 in split_parts2[1:]:
                                            fixed_buffer2[next_fix_idx2] = {
                                                'id': f"call_{_uuid2.uuid4().hex[:24]}",
                                                'type': 'function',
                                                'function': {
                                                    'name': tc_entry2['function']['name'],
                                                    'arguments': extra_args2
                                                }
                                            }
                                            next_fix_idx2 += 1
                                    else:
                                        fixed_buffer2[idx_k2] = tc_entry2
                            else:
                                fixed_buffer2[idx_k2] = tc_entry2
                        tool_calls_buffer = fixed_buffer2
                        for idx in sorted(tool_calls_buffer.keys()):
                            yield {"type": "tool_call", "tool_call": tool_calls_buffer[idx]}
                    yield {"type": "done", "finish_reason": last_finish_reason or "stop", "usage": pending_usage}
                    return
                    
            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                yield {"type": "error", "error": f"Request timed out (retried {self._max_retries} times)"}
                return
            except requests.exceptions.ConnectionError as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                yield {"type": "error", "error": f"Connection error: {str(e)}"}
                return
            except Exception as e:
                err_str = str(e)
                # InvalidChunkLength / ChunkedEncodingError etc. are retryable connection-drop errors
                is_transient = any(k in err_str for k in (
                    'InvalidChunkLength', 'ChunkedEncodingError',
                    'Connection broken', 'IncompleteRead',
                    'ConnectionReset', 'RemoteDisconnected',
                ))
                if is_transient and attempt < self._max_retries - 1:
                    wait = self._retry_delay * (attempt + 1)
                    _dbg(f"[AI Client] Connection interrupted ({err_str[:80]}), retrying in {wait}s ({attempt+1}/{self._max_retries})")
                    time.sleep(wait)
                    continue
                yield {"type": "error", "error": f"Request failed: {err_str}"}
                return

    # ============================================================
    # Non-streaming Chat (kept for compatibility)
    # ============================================================

    def chat(self,
             messages: List[Dict[str, str]],
             model: str = 'gpt-5.2',
             provider: str = 'openai',
             temperature: float = 0.17,
             max_tokens: Optional[int] = None,
             timeout: int = 60,
             tools: Optional[List[dict]] = None,
             tool_choice: str = 'auto',
             response_format: Optional[dict] = None) -> Dict[str, Any]:
        """Non-streaming Chat (legacy-compatible)."""

        if not HAS_REQUESTS:
            return {'ok': False, 'error': "The 'requests' library must be installed"}

        provider = (provider or 'openai').lower()
        api_key = self._get_api_key(provider)
        if not api_key and provider != 'ollama' and not self._is_custom_provider(provider):
            return {'ok': False, 'error': 'Missing API key'}

        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
        }
        payload['max_tokens'] = max_tokens if max_tokens else 16384
        if response_format:
            payload['response_format'] = response_format

        # GLM-4.7 specific params (only on the native GLM endpoint)
        if self.is_glm47(model) and provider == 'glm':
            payload['thinking'] = {'type': 'enabled'}

        # DeepSeek V4-Pro: enable thinking even non-streaming (it's Pro's core capability)
        if provider == 'deepseek' and 'v4-pro' in model.lower():
            payload['thinking'] = {'type': 'enabled'}
            payload['reasoning_effort'] = 'high'

        # DeepSeek / OpenAI prompt caching is enabled automatically

        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice

        headers = {
            'Content-Type': 'application/json',
        }
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        # OpenRouter requires extra headers to identify the caller (see https://openrouter.ai/docs/quickstart)
        if provider == 'openrouter':
            headers['HTTP-Referer'] = 'https://github.com/Kazama-Suichiku/Houdini-Agent'
            headers['X-OpenRouter-Title'] = 'MorfyAI - Houdini Assistant'

        # ★ Anthropic protocol branch (non-streaming)
        if self._is_anthropic_protocol(provider, model):
            return self._chat_anthropic(
                messages=messages, model=model, provider=provider,
                temperature=temperature, max_tokens=max_tokens or 4096,
                tools=tools, tool_choice=tool_choice, api_key=api_key,
                timeout=timeout,
            )
        
        for attempt in range(self._max_retries):
            try:
                response = self._http_session.post(
                    self._get_api_url(provider, model),
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                    proxies={'http': None, 'https': None}
                )
                response.raise_for_status()
                obj = response.json()
                
                choice = obj.get('choices', [{}])[0]
                message = choice.get('message', {})
                
                return {
                    'ok': True,
                    'content': message.get('content'),
                    'tool_calls': message.get('tool_calls'),
                    'finish_reason': choice.get('finish_reason'),
                    'usage': self._parse_usage(obj.get('usage', {})),
                    'raw': obj
                }
            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                return {'ok': False, 'error': 'requesttimeout'}
            except Exception as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                return {'ok': False, 'error': str(e)}
        
        return {'ok': False, 'error': 'requestfailed'}

    # ============================================================
    # Agent Loop (streamingversion) 
    # ============================================================
    
    def agent_loop_stream(self,
                          messages: List[Dict[str, Any]],
                          model: str = 'gpt-5.2',
                          provider: str = 'openai',
                          max_iterations: int = 999,
                          temperature: float = 0.17,
                          max_tokens: Optional[int] = None,
                          enable_thinking: bool = True,
                          reasoning_effort: Optional[str] = None,
                          supports_vision: bool = True,
                          tools_override: Optional[List[dict]] = None,
                          on_content: Optional[Callable[[str], None]] = None,
                          on_thinking: Optional[Callable[[str], None]] = None,
                          on_tool_call: Optional[Callable[[str, dict], None]] = None,
                          on_tool_result: Optional[Callable[[str, dict, dict], None]] = None,
                          on_tool_args_delta: Optional[Callable[[str, str, str], None]] = None,
                          on_iteration_start: Optional[Callable[[int], None]] = None,
                          on_plan_incomplete: Optional[Callable[[], Optional[str]]] = None,
                          context_limit: int = 128000) -> Dict[str, Any]:
        """streaming Agent Loop
        
        Args:
            enable_thinking: whetherenablethinkingmode (shadowrespondnativeinferencemodel  thinking parameter) 
            supports_vision: modelwhethersupportimageinput (False whenautostrip image_url content) 
            on_content: contentcallback (content) -> None
            on_thinking: thinkingcallback (content) -> None
            on_tool_call: toolcallstartcallback (name, args) -> None
            on_tool_result: toolresultcallback (name, args, result) -> None
            on_iteration_start: eachround API requeststartwhen callback (iteration) -> None
                                used for UI show "Generating..." etc.pendingstate
            on_plan_incomplete: Plan notcompletedetectcallback () -> Optional[str]
                                when AI returnpuretext (no tool_calls) whencallthiscallback. 
                                if Plan stillhasnotcompletestep, returnoneitemremindmessagestring, 
                                agent loop willwillitsinjectas user messageandresumeiterate. 
                                if Plan alreadyallpartcompleteornotneedscontinueconnect, return None. 
            context_limit: context token onlimit (default 128000) , used formainmovecompressdecidebreak
        
        Returns:
            {"ok": bool, "content": str, "final_content": str,
             "new_messages": list, "tool_calls_history": list, "iterations": int}
        """
        if not self._tool_executor:
            return {'ok': False, 'error': 'notsettoolexecute ', 'content': '', 'tool_calls_history': [], 'iterations': 0}
        
        working_messages = list(messages)
        
        # ── pre-process: notvisualmodelstripall image_url content ──
        if not supports_vision:
            n_stripped = self._strip_image_content(working_messages, keep_recent_user=0)
            if n_stripped > 0:
                _dbg(f"[AI Client] Non-vision model ({model}): stripped {n_stripped} image(s)")
        
        initial_msg_count = len(working_messages)  # trackinitialmessagecount, used forextractnewmessagechain
        tool_calls_history = []
        call_records = []  # each time API call detailfinerecord (align Cursor) 
        full_content = ""
        iteration = 0
        
        # ★ toollist: supportexternaloverride (used for Ask modeetc.scene) 
        # note: externalplugintoolalreadyin ai_tab._run_agent inmergeto tools_override, 
        # herenotagainduplicatemerge, avoidtoolduplicate. 
        effective_tools = tools_override if tools_override is not None else HOUDINI_TOOLS
        
        # accumulate usage statistics (used for cache commandinratestatistics) 
        total_usage = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'reasoning_tokens': 0,
            'total_tokens': 0,
            'cache_hit_tokens': 0,
            'cache_miss_tokens': 0,
        }
        
        # preventdeadloop: detectduplicatetoolcall
        recent_tool_signatures = []  # recent toolcallsignature
        max_tool_calls = 999  # notlimittotalcalltimecount (onlykeepconsecutiveduplicatedetect) 
        total_tool_calls = 0
        consecutive_same_calls = 0  # consecutivesamecallcountcount
        last_call_signature = None
        server_error_retries = 0    # consecutiveserviceenderrorretrycountcount
        max_server_retries = 3      # at mostretry 3 timeserviceenderror
        
        # ★ Cursor style: sameroundgorecache
        # if AI insameone turn inusesameparametercallsametool, directlyreturncacheresult
        # key: "tool_name:sorted_args_json" → value: result dict
        _turn_dedup_cache: Dict[str, dict] = {}
        
        # ★ Message-sanitize dirty flag (avoids an O(n) traversal of the message list every round)
        _needs_sanitize = True
        
        while iteration < max_iterations:
            # checkstoprequest
            if self._stop_event.is_set():
                return {
                    'ok': False,
                    'error': 'User requested stop',
                    'content': full_content,
                    'final_content': '',
                    'new_messages': working_messages[initial_msg_count:],
                    'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration,
                    'stopped': True,
                    'usage': total_usage
                }
            
            iteration += 1
            _call_start = time.time()  # Record API call start time (matches Cursor's latency statistic)
            
            # Collect this round's content and tool calls
            round_content = ""
            round_thinking = ""
            round_tool_calls = []
            should_retry = False  # error-recoverable flag
            should_abort = False  # unrecoverable-error flag
            abort_error = ""
            _round_content_started = False  # ★ Marks whether the first content chunk has been emitted this round

            # Sanitize messages before send (only needed after appending tool messages; avoids gratuitous O(n) traversal)
            if _needs_sanitize:
                working_messages = self._sanitize_working_messages(working_messages)
                _needs_sanitize = False
            
            # Diagnostic: only print a message-count summary (full content available via "Export training data")
            if iteration > 1:
                from collections import Counter
                role_counts = Counter(m.get('role', '?') for m in working_messages)
                summary = ', '.join(f"{r}={c}" for r, c in role_counts.items())
                _dbg(f"[AI Client] iteration={iteration}, messages={len(working_messages)} ({summary})")
            
            # ★ Proactive context compression (each round, starting from round 4)
            # Don't wait for context_length_exceeded; detect and compress proactively
            if iteration > 3 and len(working_messages) > 15:
                est_tokens = self._estimate_messages_tokens(working_messages, effective_tools)
                if est_tokens > context_limit * 0.85:
                    _dbg(f"[AI Client] ⚠️ Context ~{est_tokens} tokens (threshold {int(context_limit * 0.85)}), starting proactive compress")
                    working_messages = self._smart_compress_in_loop(
                        working_messages, tool_calls_history,
                        context_limit, supports_vision
                    )
                    _needs_sanitize = True
            
            # ★ notify UI newoneround API requesti.e.willstart (used forshow "Generating..." state) 
            if on_iteration_start:
                on_iteration_start(iteration)
            
            # ★ Hook: on_before_request — allowpluginmodify messages
            try:
                from .hooks import get_hook_manager as _ghm
                working_messages = _ghm().fire_filter(
                    'on_before_request', working_messages,
                    model=model, provider=provider, iteration=iteration)
            except Exception:
                pass
            
            # streamingrequest
            for chunk in self.chat_stream(
                messages=working_messages,
                model=model,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=effective_tools,
                tool_choice='auto',
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort
            ):
                # checkstoprequest
                if self._stop_event.is_set():
                    return {
                        'ok': False,
                        'error': 'User requested stop',
                        'content': full_content + round_content,
                        'final_content': round_content,
                        'new_messages': working_messages[initial_msg_count:],
                        'tool_calls_history': tool_calls_history,
                        'call_records': call_records,
                        'iterations': iteration,
                        'stopped': True,
                        'usage': total_usage
                    }
                
                chunk_type = chunk.get('type')
                
                if chunk_type == 'stopped':
                    return {
                        'ok': False,
                        'error': 'User requested stop',
                        'content': full_content + round_content,
                        'final_content': round_content,
                        'new_messages': working_messages[initial_msg_count:],
                        'tool_calls_history': tool_calls_history,
                        'call_records': call_records,
                        'iterations': iteration,
                        'stopped': True,
                        'usage': total_usage
                    }
                
                if chunk_type == 'content':
                    content = chunk.get('content', '')
                    # cleanupXMLlabel (usepre-compilepositivethen, avoideach chunk duplicatecompile) 
                    cleaned_chunk = content
                    for _pat in self._RE_CLEAN_PATTERNS:
                        cleaned_chunk = _pat.sub('', cleaned_chunk)
                    
                    # ★ fixmultiround iteration contentpasteconnect: 
                    # ifononeroundalreadyhas content (full_content notempty) , andthisroundisfirst content chunk, 
                    # autoinject \n\n paragraphpartintervalsymbol, avoid AI cross iteration  textpasteinonestart
                    if cleaned_chunk and not _round_content_started and full_content:
                        # Check whether full_content already ends with enough newlines
                        if not full_content.endswith('\n\n'):
                            sep = '\n\n' if not full_content.endswith('\n') else '\n'
                            round_content += sep
                            if on_content:
                                on_content(sep)
                        _round_content_started = True
                    elif cleaned_chunk:
                        _round_content_started = True
                    
                    round_content += cleaned_chunk
                    if on_content and cleaned_chunk:
                        on_content(cleaned_chunk)
                    # ★ Hook: on_content_chunk — pluginrealwhenfilter/convertswapcontent
                    if cleaned_chunk:
                        try:
                            from .hooks import get_hook_manager as _ghm
                            _ghm().fire('on_content_chunk', content=cleaned_chunk, iteration=iteration)
                        except Exception:
                            pass
                
                elif chunk_type == 'thinking':
                    thinking_text = chunk.get('content', '')
                    round_thinking += thinking_text
                    if on_thinking and thinking_text:
                        on_thinking(thinking_text)
                
                elif chunk_type == 'tool_args_delta':
                    if on_tool_args_delta:
                        on_tool_args_delta(
                            chunk.get('name', ''),
                            chunk.get('delta', ''),
                            chunk.get('accumulated', ''),
                        )
                
                elif chunk_type == 'tool_call':
                    tc = chunk.get('tool_call')
                    _dbg(f"[AI Client] Tool call: {tc.get('function', {}).get('name', 'unknown')}")
                    round_tool_calls.append(tc)
                
                elif chunk_type == 'error':
                    error_msg = chunk.get('error', '')
                    error_lower = error_msg.lower()
                    _dbg(f"[AI Client] Agent loop error at iteration {iteration}: {error_msg}")
                    
                    # ---- finecertainpartclasserrortype ----
                    # 1. Genuine context-limit exceeded (API explicitly says token overflow)
                    is_context_exceeded = any(k in error_lower for k in (
                        'context_length_exceeded', 'maximum context length',
                        'max_tokens', 'token limit', 'too many tokens',
                        'request too large', 'payload too large',
                        'context window', 'input too long',
                    )) or ('HTTP 413' in error_msg)
                    
                    # 2. temporarywhenservice error / connectinbreak (502/503/529 / InvalidChunkLength etc.) 
                    is_server_transient = any(k in error_msg for k in (
                        'HTTP 502', 'HTTP 503', 'HTTP 529', 'no available',
                        'InvalidChunkLength', 'ChunkedEncodingError',
                        'Connection broken', 'IncompleteRead',
                        'ConnectionReset', 'RemoteDisconnected',
                        'connecterror', 'connectinbreak',
                    ))
                    
                    # 3. compress/formatissue
                    is_format_error = ('HTTP 4' in error_msg and not is_context_exceeded and iteration > 1)
                    is_compress_fail = 'compressfailed' in error_msg
                    
                    is_recoverable = is_context_exceeded or is_server_transient or is_format_error or is_compress_fail
                    
                    if is_recoverable:
                        server_error_retries += 1
                        
                        # exceedsmaxretrytimecount → stop
                        if server_error_retries > max_server_retries:
                            _dbg(f"[AI Client] Error retried {max_server_retries} times, giving up")
                            if on_content:
                                on_content(f"\n[Failed {max_server_retries} times in a row, stopped retrying. Please try again later.]\n")
                            should_abort = True
                            abort_error = f"Failed {max_server_retries} times in a row: {error_msg}"
                            break
                        
                        cleanup_count = 0
                        
                        if is_context_exceeded:
                            # ---- truepositive contextexceedlimit: gradualenterstyletrim ----
                            _dbg(f"[AI Client] Context over limit, progressive trim (attempt #{server_error_retries})")
                            if on_content:
                                on_content(f"\n[Context limit exceeded — auto-trimming and retrying ({server_error_retries}/{max_server_retries})...]\n")
                            
                            old_len = len(working_messages)
                            working_messages = self._progressive_trim(
                                working_messages, tool_calls_history,
                                trim_level=server_error_retries,  # progressively trim harder each attempt
                                supports_vision=supports_vision
                            )
                            cleanup_count = old_len - len(working_messages)
                            
                        elif is_server_transient or is_compress_fail:
                            # ---- Transient server error: wait & retry first, don't rush to trim ----
                            wait_seconds = 5 * server_error_retries
                            if on_content:
                                on_content(f"\n[Server temporarily unavailable — retrying in {wait_seconds}s ({server_error_retries}/{max_server_retries})...]\n")
                            time.sleep(wait_seconds)
                            
                            # Only trim from the 2nd retry onward (the 1st is pure wait+retry, giving the server a chance to recover)
                            if server_error_retries >= 2:
                                _dbg(f"[AI Client] Server errors repeating, attempting light context trim")
                                old_len = len(working_messages)
                                working_messages = self._progressive_trim(
                                    working_messages, tool_calls_history,
                                    trim_level=server_error_retries - 1,  # gentler than the context-exceeded path
                                    supports_vision=supports_vision
                                )
                                cleanup_count = old_len - len(working_messages)
                            
                        else:
                            # ---- 4xx formatissue → removeendmayhasissue message ----
                            while (working_messages and cleanup_count < 20 and
                                   working_messages[-1].get('role') in ('tool', 'system')
                                   and working_messages[-1] is not messages[0]):
                                working_messages.pop()
                                cleanup_count += 1
                            if working_messages and working_messages[-1].get('role') == 'assistant':
                                working_messages.pop()
                                cleanup_count += 1
                        
                        _dbg(f"[AI Client] Retry {server_error_retries}/{max_server_retries}, removed {cleanup_count} message(s)")
                        should_retry = True
                        break  # exit for loop, backto while loopretry
                    
                    # nomethodrestore
                    should_abort = True
                    abort_error = error_msg
                    break  # exit for loop
                
                elif chunk_type == 'done':
                    # succeededcollecttorespondshould → replaceserviceenderrorretrycountcount
                    server_error_retries = 0
                    # collectset usage info (packagecontaining cache statistics) 
                    usage = chunk.get('usage', {})
                    if usage:
                        total_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                        total_usage['completion_tokens'] += usage.get('completion_tokens', 0)
                        total_usage['reasoning_tokens'] += usage.get('reasoning_tokens', 0)
                        total_usage['total_tokens'] += usage.get('total_tokens', 0)
                        total_usage['cache_hit_tokens'] += usage.get('cache_hit_tokens', 0)
                        total_usage['cache_miss_tokens'] += usage.get('cache_miss_tokens', 0)
                    
                    # ---- recordthistime API calldetails (align Cursor)  ----
                    import datetime as _dt
                    _call_latency = time.time() - _call_start
                    _rec_inp = usage.get('prompt_tokens', 0)
                    _rec_out = usage.get('completion_tokens', 0)
                    _rec_reason = usage.get('reasoning_tokens', 0)
                    _rec_chit = usage.get('cache_hit_tokens', 0)
                    _rec_cmiss = usage.get('cache_miss_tokens', 0)
                    try:
                        from morfyai.utils.token_optimizer import calculate_cost as _calc_cost
                        _rec_cost = _calc_cost(model, _rec_inp, _rec_out, _rec_chit, _rec_cmiss, _rec_reason)
                    except Exception:
                        _rec_cost = 0.0
                    call_records.append({
                        'timestamp': _dt.datetime.now().isoformat(),
                        'model': model,
                        'iteration': iteration,
                        'input_tokens': _rec_inp,
                        'output_tokens': _rec_out,
                        'reasoning_tokens': _rec_reason,
                        'cache_hit': _rec_chit,
                        'cache_miss': _rec_cmiss,
                        'total_tokens': usage.get('total_tokens', 0),
                        'latency': round(_call_latency, 2),
                        'has_tool_calls': len(round_tool_calls) > 0,
                        'estimated_cost': _rec_cost,
                    })
                    break
            
            # errorrestore: skipthisroundremaininglogic, renewrequest API
            if should_retry:
                full_content += round_content
                continue  # correctplacerenewenter while loop
            
            # notcanrestoreerror: return
            if should_abort:
                return {
                    'ok': False,
                    'error': abort_error,
                    'content': full_content,
                    'final_content': '',
                    'new_messages': working_messages[initial_msg_count:],
                    'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration,
                    'usage': total_usage
                }
            
            # ifnothastoolcall, complete
            if not round_tool_calls:
                # ★ Plan continueconnectdetect: AI outputpuretext, but Plan maystillhasnotcompletestep
                # viacallbackask UI layer Plan whethercompleted
                _plan_resume_msg = None
                if on_plan_incomplete and iteration > 1:
                    try:
                        _plan_resume_msg = on_plan_incomplete()
                    except Exception as _pe:
                        _dbg(f"[AI Client] on_plan_incomplete error: {_pe}")
                
                if _plan_resume_msg:
                    # Plan stillnotcomplete → will AI  currentreplysaveenterhistory, injectremindmessage, resumeloop
                    _dbg(f"[AI Client] ★ Plan resume: AI ended early, injecting reminder message to continue")
                    full_content += round_content
                    
                    # 1. will AI  puretextreplyas assistant messagesaveenter working_messages
                    _assistant_msg = {'role': 'assistant', 'content': round_content or ''}
                    if round_thinking:
                        _assistant_msg['reasoning_content'] = round_thinking
                    working_messages.append(_assistant_msg)
                    
                    # 2. inject "Plan notcomplete"  remindmessageas user message
                    working_messages.append({'role': 'user', 'content': _plan_resume_msg})
                    _needs_sanitize = True
                    _round_content_started = False
                    continue  # resume while loop, startnewoneround API request
                
                full_content += round_content
                # compute cache commandinrate
                prompt_total = total_usage['cache_hit_tokens'] + total_usage['cache_miss_tokens']
                if prompt_total > 0:
                    total_usage['cache_hit_rate'] = total_usage['cache_hit_tokens'] / prompt_total
                else:
                    total_usage['cache_hit_rate'] = 0
                
                _result = {
                    'ok': True,
                    'content': full_content,
                    'final_content': round_content,  # lastoneround reply (notcontaininginbetweenroundtime) 
                    'new_messages': working_messages[initial_msg_count:],  # nativetoolsubmitmutualchain
                    'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration,
                    'usage': total_usage
                }
                
                # ★ Hook: on_after_response — notifyplugin Agent Loop end
                try:
                    from .hooks import get_hook_manager as _ghm
                    _ghm().fire('on_after_response',
                               result=_result, model=model, provider=provider)
                except Exception:
                    pass
                
                return _result
            
            # addassistantmessage (ensure tool_call ID complete) 
            self._ensure_tool_call_ids(round_tool_calls)
            
            # ★ defensivepropertyfix: ensureeach tool_call   arguments ismergemethod JSON
            # Some providers (e.g., duojie) may produce concatenated invalid JSON; saving to history causes a 400 on the next round
            for _tc in round_tool_calls:
                _args_str = _tc.get('function', {}).get('arguments', '{}')
                try:
                    json.loads(_args_str)
                except (json.JSONDecodeError, ValueError):
                    # arguments nomergemethod JSON, tryextractfirstcomplete JSON object
                    _depth = 0
                    _start = -1
                    _fixed = None
                    for _ci, _ch in enumerate(_args_str):
                        if _ch == '{':
                            if _depth == 0:
                                _start = _ci
                            _depth += 1
                        elif _ch == '}':
                            _depth -= 1
                            if _depth == 0 and _start >= 0:
                                _candidate = _args_str[_start:_ci+1]
                                try:
                                    json.loads(_candidate)
                                    _fixed = _candidate
                                except:
                                    pass
                                break
                    _tc['function']['arguments'] = _fixed if _fixed else '{}'
                    _dbg(f"[AI Client] Fixed invalid tool_call arguments -> {_tc['function']['arguments'][:80]}")
            
            assistant_msg = {'role': 'assistant', 'tool_calls': round_tool_calls}
            # content asemptywhenmustpass None (null) andnotemptystring
            # Claude/Anthropic compatible withgenerationmanagereject content="" + tool_calls sharedsave
            assistant_msg['content'] = round_content or None
            # reasoning_content onlyinbackpassmessagewhenfor DeepSeek / native GLM valid
            # Duojie   reasoning_content noneedsinaftercontinuerequestinbackpass
            if self.is_reasoning_model(model) and provider in ('deepseek', 'glm'):
                assistant_msg['reasoning_content'] = round_thinking or ''
            working_messages.append(assistant_msg)
            
            # executetoolcall (web toolandrow, Houdini toolstringrow) 
            # pre-processalltoolcall
            parsed_calls = []
            for tool_call in round_tool_calls:
                tool_id = tool_call.get('id', '')
                function = tool_call.get('function', {})
                tool_name = function.get('name', '')
                args_str = function.get('arguments', '{}')
                try:
                    arguments = json.loads(args_str)
                except:
                    arguments = {}
                parsed_calls.append((tool_id, tool_name, arguments, tool_call))

            # ★ sameroundgore: purequeryclasstoolusesameparameterduplicatecallwhendirectlyreturncache
            # Only dedupe side-effect-free query tools (execute_python/run_skill/web_search etc. have side effects — don't dedupe)
            _DEDUP_TOOLS = frozenset({
                'get_network_structure', 'get_node_parameters', 'list_children',
                'read_selection', 'search_node_types', 'semantic_search_nodes',
                'find_nodes_by_param', 'check_errors', 'search_local_doc',
                'get_houdini_node_doc', 'get_node_inputs', 'list_skills',
                'perf_stop_and_report',
            })
            
            # partleavecanandrowtool (web + shell) and Houdini tool (needsmainthreadstringrow) 
            _ASYNC_TOOL_NAMES = frozenset({'web_search', 'fetch_webpage', 'execute_shell'})
            async_calls = [(i, pc) for i, pc in enumerate(parsed_calls) if pc[1] in _ASYNC_TOOL_NAMES]
            houdini_calls = [(i, pc) for i, pc in enumerate(parsed_calls) if pc[1] not in _ASYNC_TOOL_NAMES]

            # resultslotbit: keeporiginalorderorder
            results_ordered = [None] * len(parsed_calls)
            dedup_flags = [False] * len(parsed_calls)  # markwhichsomeiscachecommandin

            # --- firstcheckgorecache ---
            for idx, (tid, tname, targs, _tc) in enumerate(parsed_calls):
                dedup_key = f"{tname}:{json.dumps(targs, sort_keys=True)}"
                if tname in _DEDUP_TOOLS and dedup_key in _turn_dedup_cache:
                    # ★ cachecommandin: directlyreturnbefore result
                    results_ordered[idx] = _turn_dedup_cache[dedup_key]
                    dedup_flags[idx] = True
                    _dbg(f"[AI Client] ♻️ Same-round dedup hit: {tname}({json.dumps(targs, ensure_ascii=False)[:80]})")

            # partleavenotcache call
            uncached_async = [(i, pc) for i, pc in enumerate(parsed_calls) 
                             if pc[1] in _ASYNC_TOOL_NAMES and not dedup_flags[i]]
            uncached_houdini = [(i, pc) for i, pc in enumerate(parsed_calls) 
                               if pc[1] not in _ASYNC_TOOL_NAMES and not dedup_flags[i]]

            # --- androwexecutenotcache  async tool (web + shell)  ---
            if len(uncached_async) > 1:
                import concurrent.futures
                def _exec_async(idx_pc):
                    idx, (tid, tname, targs, _tc) = idx_pc
                    if tname == 'web_search':
                        return idx, self._execute_web_search(targs)
                    elif tname == 'fetch_webpage':
                        return idx, self._execute_fetch_webpage(targs)
                    else:  # execute_shell
                        return idx, self._tool_executor(tname, **targs)
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(uncached_async))) as pool:
                    for idx, result in pool.map(_exec_async, uncached_async):
                        results_ordered[idx] = result
            elif len(uncached_async) == 1:
                idx, (tid, tname, targs, _tc) = uncached_async[0]
                if tname == 'web_search':
                    results_ordered[idx] = self._execute_web_search(targs)
                elif tname == 'fetch_webpage':
                    results_ordered[idx] = self._execute_fetch_webpage(targs)
                else:  # execute_shell
                    results_ordered[idx] = self._tool_executor(tname, **targs)

            # --- executenotcache  Houdini tool (needsmainthread)  ---
            # ★ Read-only tool batch execution: reduce N signal round-trips to 1
            _BATCH_READONLY = frozenset({
                'get_network_structure', 'get_node_parameters', 'list_children',
                'read_selection', 'search_node_types', 'semantic_search_nodes',
                'find_nodes_by_param', 'get_node_inputs', 'check_errors',
                'search_local_doc', 'get_houdini_node_doc', 'list_skills',
                'get_node_positions', 'list_network_boxes',
                'perf_start_profile', 'perf_stop_and_report',
            })
            # partleaveread-onlyandwritetool
            readonly_batch = [(i, pc) for i, pc in uncached_houdini if pc[1] in _BATCH_READONLY]
            mutating_calls = [(i, pc) for i, pc in uncached_houdini if pc[1] not in _BATCH_READONLY]

            # batchexecuteread-onlytool (ifhas batch executor and >1 read-onlycall) 
            if len(readonly_batch) > 1 and self._batch_tool_executor:
                batch_input = [(tname, targs) for _, (_, tname, targs, _) in readonly_batch]
                try:
                    batch_results = self._batch_tool_executor(batch_input)
                    for (idx, _), result in zip(readonly_batch, batch_results):
                        results_ordered[idx] = result
                except Exception as e:
                    _dbg(f"[AI Client] Batch execution failed, falling back to serial: {e}")
                    for idx, (tid, tname, targs, _tc) in readonly_batch:
                        results_ordered[idx] = self._tool_executor(tname, **targs)
            else:
                # singleread-onlytoolorno batch executor → stringrow
                for idx, (tid, tname, targs, _tc) in readonly_batch:
                    results_ordered[idx] = self._tool_executor(tname, **targs)

            # Write tools always run serially (have side effects, order-sensitive)
            for idx, (tid, tname, targs, _tc) in mutating_calls:
                results_ordered[idx] = self._tool_executor(tname, **targs)

            # ★ Early abort: skip redundant queries
            # When already-executed tool results provide enough info, skip remaining same-class queries
            _early_skip_count = 0
            if len(parsed_calls) > 2:
                # collectsetalreadyhasresultin info
                _check_errors_paths = set()
                _empty_network_paths = set()
                for idx, (_, tname, targs, _) in enumerate(parsed_calls):
                    if results_ordered[idx] is None:
                        continue
                    result = results_ordered[idx]
                    # check_errors discovererror → samepath  get_node_parameters notagainneeds
                    if tname == 'check_errors' and result.get('success'):
                        r_text = result.get('result', '')
                        if 'error' in r_text or 'error' in r_text.lower():
                            path = targs.get('node_path', '')
                            if path:
                                _check_errors_paths.add(path)
                    # get_network_structure returnempty → samepath subquerynotneeds
                    if tname == 'get_network_structure' and result.get('success'):
                        r_text = result.get('result', '')
                        if 'nodecount: 0' in r_text or 'Nodes: 0' in r_text or not r_text.strip():
                            path = targs.get('network_path', '') or targs.get('node_path', '')
                            if path:
                                _empty_network_paths.add(path)

                # markcanskip tool (onlyforstillnotexecute  readonly call) 
                for idx, (tid, tname, targs, _tc) in enumerate(parsed_calls):
                    if results_ordered[idx] is not None:
                        continue  # alreadyhasresult
                    path = targs.get('node_path', '') or targs.get('network_path', '')
                    # rule 1: check_errors alreadydiscovererror → skipsamepath  get_node_parameters
                    if tname == 'get_node_parameters' and path in _check_errors_paths:
                        results_ordered[idx] = {
                            "success": True,
                            "result": f"[alreadyskip] {path} alreadyhaserrorinfo, pleasefirstfixerror. "
                        }
                        _early_skip_count += 1
                    # rule 2: networkasempty → skip list_children / get_node_parameters
                    elif tname in ('list_children', 'get_node_parameters') and path in _empty_network_paths:
                        results_ordered[idx] = {
                            "success": True,
                            "result": f"[alreadyskip] {path} networkasempty, nosubnode. "
                        }
                        _early_skip_count += 1
                if _early_skip_count > 0:
                    _dbg(f"[AI Client] ⏭️ Early termination: skipped {_early_skip_count} redundant query(ies)")
            
            # --- Cache maintenance ---
            # ifthisroundhasoperationclasstool (create/delete/connectnodeetc.) , clearremovenetworkstructurerelatedcache
            # becauseoperationchangechangenetworkstate, beforecache queryresultmayalreadypassedperiod
            _NETWORK_MUTATING_TOOLS = frozenset({
                'create_node', 'create_nodes_batch', 'delete_node', 'connect_nodes',
                'create_wrangle_node', 'copy_node', 'set_display_flag', 'undo_redo',
            })
            has_mutation = any(
                pc[1] in _NETWORK_MUTATING_TOOLS 
                for idx_m, pc in enumerate(parsed_calls) 
                if not dedup_flags[idx_m]
            )
            if has_mutation:
                # clearremove get_network_structure / list_children / check_errors  cache
                keys_to_remove = [k for k in _turn_dedup_cache 
                                  if k.startswith(('get_network_structure:', 'list_children:', 'check_errors:'))]
                for k in keys_to_remove:
                    del _turn_dedup_cache[k]
            
            # willnewexecute querytoolresultwritegorecache
            for idx, (tid, tname, targs, _tc) in enumerate(parsed_calls):
                if not dedup_flags[idx] and tname in _DEDUP_TOOLS and results_ordered[idx]:
                    dedup_key = f"{tname}:{json.dumps(targs, sort_keys=True)}"
                    _turn_dedup_cache[dedup_key] = results_ordered[idx]

            # --- statsoneprocessresult (keeporiginalorderorder)  ---
            should_break_tool_limit = False
            for i, (tool_id, tool_name, arguments, _tc) in enumerate(parsed_calls):
                result = results_ordered[i]

                # preventdeadloop: detectduplicatetoolcall
                total_tool_calls += 1
                call_signature = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"

                if total_tool_calls > max_tool_calls:
                    _dbg(f"[AI Client] ⚠️ Reached max tool-call limit ({max_tool_calls})")
                    should_break_tool_limit = True
                    break

                if call_signature == last_call_signature:
                    consecutive_same_calls += 1
                else:
                    consecutive_same_calls = 1
                    last_call_signature = call_signature

                # callback
                if on_tool_call:
                    on_tool_call(tool_name, arguments)

                tool_calls_history.append({
                    'tool_name': tool_name,
                    'arguments': arguments,
                    'result': result
                })

                if on_tool_result:
                    on_tool_result(tool_name, arguments, result)

                result_content = self._compress_tool_result(tool_name, result)
                
                # ★ gorecommandinwhenappendhint, guideimport AI don'tagainduplicatecall
                if dedup_flags[i]:
                    result_content = f"[cache] thisroundalreadyusesameparametercallpassedthistool, or lessisbefore result (noneedsagaintimecall) :\n{result_content}"

                working_messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_id,
                    'content': result_content
                })
                _needs_sanitize = True  # Added a tool message; next round needs sanitization

                # ★ viewportscreenshotinject: iftoolreturn _viewport_image, 
                # appendoneitempackagecontainingimage  user message, letmodelcanvisualanalyze
                if supports_vision and result.get('_viewport_image'):
                    _img_b64 = result['_viewport_image']
                    _img_mt = result.get('_image_media_type', 'image/jpeg')
                    working_messages.append({
                        'role': 'user',
                        'content': [
                            {"type": "text", "text": "[viewport snapshot attached — please analyze the current viewport state, check for visual issues or confirm the result is correct]"},
                            {"type": "image_url", "image_url": {"url": f"data:{_img_mt};base64,{_img_b64}"}}
                        ]
                    })
                    _dbg(f"[AI Client] 📸 Viewport screenshot injected ({len(_img_b64)//1024}KB base64)")

            if should_break_tool_limit:
                return {
                    'ok': True,
                    'content': full_content + f"\n\nalreadyreachtotoolcalltimecountlimit({max_tool_calls}), autostop. ",
                    'final_content': f"\n\nalreadyreachtotoolcalltimecountlimit({max_tool_calls}), autostop. ",
                    'new_messages': working_messages[initial_msg_count:],
                    'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration,
                    'usage': total_usage
                }
            
            # multiroundthinkingguideimport: inlastoneitemtoolresultafterattachhint
            # detectthisroundwhetherhastoolcall failed
            _round_failed = False
            for _ri, (_tid, _tn, _ta, _tc) in enumerate(parsed_calls):
                if not results_ordered[_ri].get('success'):
                    _round_failed = True
                    break

            if working_messages and working_messages[-1].get('role') == 'tool':
                if _round_failed:
                    working_messages[-1]['content'] += (
                        "\n\n[Note: the tool call above returned an error — this is a tool-layer parameter or execution error, "
                        'noHoudininodecookingerror, noneedscallcheck_errors. '
                        'pleasedirectlybased onerrorinfofixpositiveparameterafterrenewcallthistool. ]'
                    )
                if enable_thinking:
                    working_messages[-1]['content'] += (
                        "\n\n[Reminder: your next reply MUST start with a <think> tag. "
                        "Inside the tag, analyze the latest tool-execution results and current progress, "
                        "review the Todo list to see which steps are complete (use update_todo to mark done), "
                        "confirm the next step's plan, then resume execution. Do not skip the <think> tag.]"
                    )
            
            # savecurrentroundtime content
            full_content += round_content
        
        # ifloopendbutcontentasempty, andhastoolcallhistory, forceneedrequestgeneratesummary
        if not full_content.strip() and tool_calls_history:
            _dbg("[AI Client] ⚠️ Stream mode: tool calls done but no reply content, forcing summary generation")
            # lastoncerequest, forceneedrequestsummary
            working_messages.append({
                'role': 'user',
                'content': 'pleasegeneratefinalsummary, descriptioncompleted operationandresult. '
            })
            
            # againtimerequestgeneratesummary
            summary_content = ""
            for chunk in self.chat_stream(
                messages=working_messages,
                model=model,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens or 500,  # limitsummarylength
                tools=None,  # summarystagenotneedstool
                tool_choice=None
            ):
                if chunk.get('type') == 'content':
                    content = chunk.get('content', '')
                    summary_content += content
                    if on_content:
                        on_content(content)
                elif chunk.get('type') == 'done':
                    break
            
            full_content = summary_content if summary_content else full_content
        
        _dbg(f"[AI Client] Reached max iterations ({iteration})")
        # compute cache commandinrate
        prompt_total = total_usage['cache_hit_tokens'] + total_usage['cache_miss_tokens']
        if prompt_total > 0:
            total_usage['cache_hit_rate'] = total_usage['cache_hit_tokens'] / prompt_total
        else:
            total_usage['cache_hit_rate'] = 0
        return {
            'ok': True,
            'content': full_content if full_content.strip() else "(toolcallcomplete, butnotgeneratereply)",
            'final_content': '',  # max iterations whennoclearcertain finalreply
            'new_messages': working_messages[initial_msg_count:],
            'tool_calls_history': tool_calls_history,
            'call_records': call_records,
            'iterations': iteration,
            'usage': total_usage
        }

    def _execute_web_search(self, arguments: dict) -> dict:
        """Run a web search (general use: weather / news / docs / any topic)."""
        query = arguments.get('query', '')
        max_results = arguments.get('max_results', 5)
        
        if not query:
            return {"success": False, "error": "missingSearch keyword"}
        
        result = self._web_searcher.search(query, max_results)
        
        if result.get('success'):
            items = result.get('results', [])
            if not items:
                return {"success": True, "result": f"search '{query}' notfindtoresult. cantryswapusedifferentkeyword. "}
            
            # formatizationresult: title + URL + summary
            lines = [f"search '{query}'  result (comesource: {result.get('source', 'Unknown')}, shared {len(items)} item) : \n"]
            for i, item in enumerate(items, 1):
                lines.append(f"{i}. {item.get('title', 'notitle')}")
                lines.append(f"   URL: {item.get('url', '')}")
                snippet = item.get('snippet', '')
                if snippet:
                    lines.append(f"   summary: {snippet[:300]}")
                lines.append("")
            
            lines.append("Hint: to view full details, use fetch_webpage(url=...) to fetch the page body. When referencing information, you MUST add an inline citation at the end of the paragraph in the form [Source: title](URL). Do NOT repeat the search with the same keywords.")
            
            return {"success": True, "result": "\n".join(lines)}
        else:
            return {"success": False, "error": result.get('error', 'searchfailed')}

    def _execute_fetch_webpage(self, arguments: dict) -> dict:
        """Fetch web page content (paginated return, supports paging)."""
        url = arguments.get('url', '')
        start_line = arguments.get('start_line', 1)
        
        if not url:
            return {"success": False, "error": "missing URL"}
        
        # ensure start_line mergemethod
        try:
            start_line = max(1, int(start_line))
        except (TypeError, ValueError):
            start_line = 1
        
        result = self._web_searcher.fetch_page_content(url, max_lines=80, start_line=start_line)
        
        if result.get('success'):
            content = result.get('content', '')
            return {"success": True, "result": f"netpagebody text ({url}) : \n\n{content}"}
        else:
            return {"success": False, "error": result.get('error', 'getfailed')}

    # keepcompatible withproperty
    def agent_loop(self, *args, **kwargs):
        """compatible witholdconnectport"""
        return self.agent_loop_stream(*args, **kwargs)

    # ============================================================
    # JSON parsemode (used fornot supported Function Calling  model) 
    # ============================================================
    
    def _supports_function_calling(self, provider: str, model: str) -> bool:
        """checkmodelwhethersupportnative Function Calling"""
        # Ollama modeldefaultnot supported
        if provider == 'ollama':
            return False
        # Custom provider based onuserconfigdecidefixed
        if self._is_custom_provider(provider):
            return self._custom_cfg(provider).get('supports_fc', True)
        # Other cloud models all support it
        return True
    
    def _get_json_mode_system_prompt(self, tools_list: Optional[List[dict]] = None) -> str:
        """get JSON mode systemhint (execute mode) """
        # buildtoollistdescription
        tool_descriptions = []
        for tool in (tools_list or HOUDINI_TOOLS):
            func = tool['function']
            params = func.get('parameters', {}).get('properties', {})
            required = func.get('parameters', {}).get('required', [])
            
            param_desc = []
            for pname, pinfo in params.items():
                req_mark = "(required)" if pname in required else "(optional)"
                param_desc.append(f"    - {pname} {req_mark}: {pinfo.get('description', '')}")
            
            tool_descriptions.append(f"""
**{func['name']}** - {func['description']}
parameter:
{chr(10).join(param_desc) if param_desc else '    no'}
""")
        
        return f"""You are a Houdini executor. Only execute — do not think, do not explain.

STRICTLY DISALLOWED (violating these wastes tokens):
- Do not generate any thinking process, reasoning steps, or analysis
- Do not say "why", "let me first", "I need"
- Do not describe steps one by one or explain anything
- Do not output any non-executable content

ALLOWED ONLY:
- Directly call tools to execute operations
- Directly give the execution result (1 sentence max)
- Do not output any thinking content

Node-path output convention:
- When mentioning a node in a reply, always use the full absolute path (e.g., /obj/geo1/box1), never just the node name (e.g., box1)
- The path will auto-render as a clickable link that the user can use to jump to the node

Tool-call parameter convention (HIGHEST PRIORITY):
- Before calling, confirm all required parameters are filled in; missing required params cause failure
- node_path must be the full absolute path (e.g., "/obj/geo1/box1"), never just the node name
- Parameter value types must be correct: string / number / boolean / array — don't mix them
- When a tool returns a "missing parameter" error, fix the parameter and retry directly — do not call check_errors
- Every call must fully fill in all required parameters; don't assume the system remembers them from a previous call

Safe-operation rules (MUST follow):
- First time inspecting a network, call get_network_structure; if already queried this turn, do not call it again (the system caches same-turn query results)
- Before setting parameters, use get_node_parameters to look up the correct parameter name and type — don't guess
- Inside execute_python, always None-check: node = hou.node(path); if node: ...
- After creating a node, operate on the returned path — don't guess the path
- Before connecting nodes, confirm both nodes exist

Mandatory pre-completion check (forced at end of task):
- Call verify_and_summarize for auto-detection (includes a built-in network check; no need to call get_network_structure first)
- If issues are found, fix them, then call verify_and_summarize again and pass through

## Tool-call format

```json
{{"tool": "tool_name", "args": {{"parameter_name": "value"}}}}
```

Rules:
1. Only one tool call at a time
2. Each tool call goes in its own JSON code block
3. After calling, wait for the result before continuing
4. Don't explain — execute directly
5. Query first to confirm, then operate
6. Before calling, verify all required parameters are filled; don't omit node_path or other required params
7. node_path must be the full absolute path (e.g., "/obj/geo1/box1"), never just the node name

## Available tools

{chr(10).join(tool_descriptions)}

## Example

createnode (notresolverelease, directlyexecute) :
```json
{{"tool": "create_node", "args": {{"node_type": "box"}}}}
```
"""
    
    def _parse_json_tool_calls(self, content: str) -> List[Dict]:
        """fromtextcontentinparse JSON format toolcall (improvedversion: supportmultikindformat) """
        import re
        
        tool_calls = []
        
        # 1. cleanupXMLlabel (ifAIerroroutputXMLformat) 
        content = re.sub(r'</?tool_call[^>]*>', '', content)
        content = re.sub(r'<arg_key>([^<]+)</arg_key>\s*<arg_value>([^<]+)</arg_value>', r'"\1": "\2"', content)
        
        # 2. match ```json ... ``` codeblock
        json_blocks = re.findall(r'```(?:json)?\s*\n?({[^`]+})\s*\n?```', content, re.DOTALL)
        
        # 3. ifnothascodeblock, trydirectlymatchJSONobject
        if not json_blocks:
            # trymatchindependentstand JSONobject (notincodeblockin) 
            json_pattern = r'\{\s*"(?:tool|name)"\s*:\s*"[^"]+"\s*,\s*"(?:args|arguments)"\s*:\s*\{[^}]+\}\s*\}'
            json_blocks = re.findall(json_pattern, content, re.DOTALL)
        
        for block in json_blocks:
            try:
                # cleanupmay formatissue
                block = block.strip()
                # fixcommon JSONformaterror
                block = re.sub(r',\s*}', '}', block)  # remove trailing comma before object close
                block = re.sub(r',\s*]', ']', block)  # remove trailing comma before array close
                
                data = json.loads(block)
                if 'tool' in data:
                    tool_calls.append({
                        'name': data['tool'],
                        'arguments': data.get('args', data.get('arguments', {}))
                    })
                elif 'name' in data:
                    # compatible with {"name": "xxx", "arguments": {...}} format
                    tool_calls.append({
                        'name': data['name'],
                        'arguments': data.get('arguments', data.get('args', {}))
                    })
            except (json.JSONDecodeError, KeyError) as e:
                # recordparse failedbutnotinbreak
                _dbg(f"[AI Client] JSON parse failed: {e}, content: {block[:100]}")
                continue
        
        return tool_calls
    
    def agent_loop_json_mode(self,
                              messages: List[Dict[str, Any]],
                              model: str = 'qwen2.5:14b',
                              provider: str = 'ollama',
                              max_iterations: int = 999,
                              temperature: float = 0.17,
                              max_tokens: Optional[int] = None,
                              enable_thinking: bool = True,
                              reasoning_effort: Optional[str] = None,
                              supports_vision: bool = True,
                              tools_override: Optional[List[dict]] = None,
                              on_content: Optional[Callable[[str], None]] = None,
                              on_thinking: Optional[Callable[[str], None]] = None,
                              on_tool_call: Optional[Callable[[str, dict], None]] = None,
                              on_tool_result: Optional[Callable[[str, dict, dict], None]] = None,
                              on_tool_args_delta: Optional[Callable[[str, str, str], None]] = None,
                              on_iteration_start: Optional[Callable[[int], None]] = None,
                              on_plan_incomplete: Optional[Callable[[], Optional[str]]] = None,
                              context_limit: int = 128000) -> Dict[str, Any]:
        """JSON mode Agent Loop (used fornot supported Function Calling  model) """
        
        if not self._tool_executor:
            return {'ok': False, 'error': 'notsettoolexecute ', 'content': '', 'tool_calls_history': [], 'iterations': 0}
        
        # ★ toollist: supportexternaloverride (used for Ask modeetc.scene) 
        # note: externalplugintoolalreadyin ai_tab._run_agent inmergeto tools_override, 
        # herenotagainduplicatemerge, avoidtoolduplicate. 
        effective_tools = tools_override if tools_override is not None else HOUDINI_TOOLS
        
        # add JSON modesystemhint
        json_system_prompt = self._get_json_mode_system_prompt(effective_tools)
        working_messages = []
        
        # processmessage, infirst system messageafterappend JSON modedescription
        system_found = False
        for msg in messages:
            if msg.get('role') == 'system' and not system_found:
                working_messages.append({
                    'role': 'system',
                    'content': msg.get('content', '') + '\n\n' + json_system_prompt
                })
                system_found = True
            else:
                working_messages.append(msg)
        
        if not system_found:
            working_messages.insert(0, {'role': 'system', 'content': json_system_prompt})
        
        # ── pre-process: notvisualmodelstripall image_url content ──
        if not supports_vision:
            n_stripped = self._strip_image_content(working_messages, keep_recent_user=0)
            if n_stripped > 0:
                _dbg(f"[AI Client] Non-vision model ({model}): stripped {n_stripped} image(s)")
        
        tool_calls_history = []
        call_records = []  # each time API call detailfinerecord (align Cursor) 
        full_content = ""
        iteration = 0
        self._json_thinking_buffer = ""  # initializationthinkingbuffersection
        
        # accumulate usage statistics (used for cache commandinratestatistics) 
        total_usage = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'reasoning_tokens': 0,
            'total_tokens': 0,
            'cache_hit_tokens': 0,
            'cache_miss_tokens': 0,
        }
        
        # preventdeadloop: detectduplicatetoolcall
        max_tool_calls = 999  # notlimittotalcalltimecount (onlykeepconsecutiveduplicatedetect) 
        total_tool_calls = 0
        consecutive_same_calls = 0
        last_call_signature = None
        server_error_retries = 0    # consecutiveserviceenderrorretrycountcount
        max_server_retries = 3      # at mostretry 3 timeserviceenderror
        
        while iteration < max_iterations:
            if self._stop_event.is_set():
                return {
                    'ok': False, 'error': 'userstoprequest',
                    'content': full_content, 'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration, 'stopped': True, 'usage': total_usage
                }
            
            iteration += 1
            _call_start = time.time()  # Record API call start time (matches Cursor's latency statistic)
            round_content = ""
            
            # ★ mainmovestylecontextcompress (fromthe 4 roundstartcheck, replacement foroldsimplecutbreaklogic) 
            if iteration > 3 and len(working_messages) > 15:
                est_tokens = self._estimate_messages_tokens(working_messages, effective_tools)
                if est_tokens > context_limit * 0.85:
                    _dbg(f"[AI Client] ⚠️ JSON-mode context ~{est_tokens} tokens (threshold {int(context_limit * 0.85)}), starting proactive compress")
                    working_messages = self._smart_compress_in_loop(
                        working_messages, tool_calls_history,
                        context_limit, supports_vision
                    )
            elif iteration > 1 and len(working_messages) > 20:
                # lightweightdefensive: onlyinnottriggermainmovecompresswhendosimplecutbreak
                protect_start = max(1, len(working_messages) - 6)
                for i, m in enumerate(working_messages):
                    if i == 0 or i >= protect_start:
                        continue
                    role = m.get('role', '')
                    if role == 'user':
                        continue
                    c = m.get('content') or ''
                    if role == 'tool' and len(c) > 400:
                        m['content'] = self._summarize_tool_content(c, 400)
                    elif role == 'assistant' and len(c) > 600:
                        m['content'] = c[:600] + '...[alreadycutbreak]'
            
            # ★ notify UI newoneround API requesti.e.willstart (used forshow "Generating..." state) 
            if on_iteration_start:
                on_iteration_start(iteration)
            
            # streamingrequest (notpass tools parameter) 
            for chunk in self.chat_stream(
                messages=working_messages,
                model=model,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=None,  # JSON modenotusenativetool
                tool_choice=None
            ):
                if self._stop_event.is_set():
                    return {
                        'ok': False, 'error': 'userstoprequest',
                        'content': full_content + round_content,
                        'tool_calls_history': tool_calls_history,
                        'call_records': call_records,
                        'iterations': iteration, 'stopped': True, 'usage': total_usage
                    }
                
                chunk_type = chunk.get('type')
                
                if chunk_type == 'content':
                    content = chunk.get('content', '')
                    round_content += content
                    if on_content:
                        on_content(content)
                
                elif chunk_type == 'thinking':
                    thinking_text = chunk.get('content', '')
                    if on_thinking and thinking_text:
                        on_thinking(thinking_text)
                
                elif chunk_type == 'error':
                    err_msg = chunk.get('error', '')
                    err_lower = err_msg.lower()
                    
                    # finecertainpartclasserror
                    is_context_exceeded = any(k in err_lower for k in (
                        'context_length_exceeded', 'maximum context length',
                        'max_tokens', 'token limit', 'too many tokens',
                        'request too large', 'payload too large',
                        'context window', 'input too long',
                    )) or ('HTTP 413' in err_msg)
                    is_server_transient = any(k in err_msg for k in (
                        'HTTP 502', 'HTTP 503', 'HTTP 529', 'compressfailed', 'no available'
                    ))
                    
                    if is_context_exceeded or is_server_transient:
                        server_error_retries += 1
                        if server_error_retries > max_server_retries:
                            if on_content:
                                on_content(f"\n[Failed {max_server_retries} times in a row, stopped retrying.]\n")
                            return {
                                'ok': False, 'error': f"Repeated failures: {err_msg}",
                                'content': full_content, 'tool_calls_history': tool_calls_history,
                                'call_records': call_records,
                                'iterations': iteration, 'usage': total_usage
                            }
                        
                        if is_context_exceeded:
                            # contextexceedlimit: standi.e.trim
                            if on_content:
                                on_content(f"\n[Context limit exceeded — auto-trimming and retrying ({server_error_retries}/{max_server_retries})...]\n")
                            working_messages = self._progressive_trim(
                                working_messages, tool_calls_history,
                                trim_level=server_error_retries,
                                supports_vision=supports_vision
                            )
                        else:
                            # temporarywhenservice error: etc.pending, the2timestartonly thentrim
                            wait_seconds = 5 * server_error_retries
                            if on_content:
                                on_content(f"\n[Server temporarily unavailable — retrying in {wait_seconds}s ({server_error_retries}/{max_server_retries})...]\n")
                            time.sleep(wait_seconds)
                            if server_error_retries >= 2:
                                working_messages = self._progressive_trim(
                                    working_messages, tool_calls_history,
                                    trim_level=server_error_retries - 1,
                                    supports_vision=supports_vision
                                )
                        break  # exit for, backto while retry
                    return {
                        'ok': False, 'error': err_msg,
                        'content': full_content, 'tool_calls_history': tool_calls_history,
                        'call_records': call_records,
                        'iterations': iteration, 'usage': total_usage
                    }
                
                elif chunk_type == 'done':
                    # succeededcollecttorespondshould → replaceserviceenderrorretrycountcount
                    server_error_retries = 0
                    # collectset usage info (packagecontaining cache statistics) 
                    usage = chunk.get('usage', {})
                    if usage:
                        total_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                        total_usage['completion_tokens'] += usage.get('completion_tokens', 0)
                        total_usage['reasoning_tokens'] += usage.get('reasoning_tokens', 0)
                        total_usage['total_tokens'] += usage.get('total_tokens', 0)
                        total_usage['cache_hit_tokens'] += usage.get('cache_hit_tokens', 0)
                        total_usage['cache_miss_tokens'] += usage.get('cache_miss_tokens', 0)
                    
                    # ---- recordthistime API calldetails (align Cursor)  ----
                    import datetime as _dt
                    _call_latency = time.time() - _call_start
                    _rec_inp = usage.get('prompt_tokens', 0)
                    _rec_out = usage.get('completion_tokens', 0)
                    _rec_reason = usage.get('reasoning_tokens', 0)
                    _rec_chit = usage.get('cache_hit_tokens', 0)
                    _rec_cmiss = usage.get('cache_miss_tokens', 0)
                    try:
                        from morfyai.utils.token_optimizer import calculate_cost as _calc_cost
                        _rec_cost = _calc_cost(model, _rec_inp, _rec_out, _rec_chit, _rec_cmiss, _rec_reason)
                    except Exception:
                        _rec_cost = 0.0
                    call_records.append({
                        'timestamp': _dt.datetime.now().isoformat(),
                        'model': model,
                        'iteration': iteration,
                        'input_tokens': _rec_inp,
                        'output_tokens': _rec_out,
                        'reasoning_tokens': _rec_reason,
                        'cache_hit': _rec_chit,
                        'cache_miss': _rec_cmiss,
                        'total_tokens': usage.get('total_tokens', 0),
                        'latency': round(_call_latency, 2),
                        'has_tool_calls': False,
                        'estimated_cost': _rec_cost,
                    })
                    break
            
            # cleanupcontentin XMLlabelandformatissue (usepre-compilepositivethen) 
            cleaned_content = round_content
            for _pat in self._RE_CLEAN_PATTERNS:
                cleaned_content = _pat.sub('', cleaned_content)
            # cleanupothermay XMLlabel
            cleaned_content = re.sub(r'<[^>]+>', '', cleaned_content)  # cleanupallremaining XMLlabel
            
            # parse JSON toolcall
            tool_calls = self._parse_json_tool_calls(cleaned_content)
            
            # ifnothastoolcall, checkwhethercomplete
            if not tool_calls:
                # cleanupafter contentaddtofull_content (onlyaddonce, avoidduplicate) 
                if cleaned_content.strip():
                    # checkwhetherwithalreadyhascontentduplicate (avoidduplicateadd) 
                    if cleaned_content.strip() not in full_content:
                        full_content += cleaned_content
                # ifcontentasemptyoronlyhasemptywhite, checkwhetherneedsresume
                if not cleaned_content.strip() and tool_calls_history:
                    # hastoolcallhistorybutnocontent, resumeloopetc.pendingsummary
                    continue
                
                # ★ Plan continueconnectdetect (JSON mode) 
                _plan_resume_msg = None
                if on_plan_incomplete and iteration > 1:
                    try:
                        _plan_resume_msg = on_plan_incomplete()
                    except Exception as _pe:
                        _dbg(f"[AI Client] on_plan_incomplete error (json mode): {_pe}")
                
                if _plan_resume_msg:
                    _dbg(f"[AI Client] ★ Plan resume (JSON mode): AI ended early, injecting reminder message to continue")
                    working_messages.append({'role': 'assistant', 'content': cleaned_content or ''})
                    working_messages.append({'role': 'user', 'content': _plan_resume_msg})
                    continue
                
                # compute cache commandinrate
                prompt_total = total_usage['cache_hit_tokens'] + total_usage['cache_miss_tokens']
                if prompt_total > 0:
                    total_usage['cache_hit_rate'] = total_usage['cache_hit_tokens'] / prompt_total
                else:
                    total_usage['cache_hit_rate'] = 0
                return {
                    'ok': True,
                    'content': full_content,
                    'tool_calls_history': tool_calls_history,
                    'call_records': call_records,
                    'iterations': iteration,
                    'usage': total_usage
                }
            
            # addassistantmessage (usecleanupafter content, butdon'tduplicateaddtofull_content) 
            json_assistant_msg = {'role': 'assistant', 'content': cleaned_content}
            # reasoning_content onlyinbackpasswhenfor DeepSeek / native GLM valid (Duojie noneedsbackpass) 
            if self.is_reasoning_model(model) and provider in ('deepseek', 'glm'):
                json_assistant_msg['reasoning_content'] = ''
            working_messages.append(json_assistant_msg)
            
            # executetoolcall (web toolandrow, Houdini toolstringrow) 
            tool_results = []

            _ASYNC_TOOL_NAMES_JSON = frozenset({'web_search', 'fetch_webpage', 'execute_shell'})
            async_tc = [(i, tc) for i, tc in enumerate(tool_calls) if tc['name'] in _ASYNC_TOOL_NAMES_JSON]
            houdini_tc = [(i, tc) for i, tc in enumerate(tool_calls) if tc['name'] not in _ASYNC_TOOL_NAMES_JSON]

            # resultslotbit
            exec_results = [None] * len(tool_calls)

            # androw async tool (web + shell) 
            if len(async_tc) > 1:
                import concurrent.futures
                def _exec_async_json(idx_tc):
                    idx, tc = idx_tc
                    tname, targs = tc['name'], tc['arguments']
                    if tname == 'web_search':
                        return idx, self._execute_web_search(targs)
                    elif tname == 'fetch_webpage':
                        return idx, self._execute_fetch_webpage(targs)
                    else:  # execute_shell
                        return idx, self._tool_executor(tname, **targs)
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(async_tc))) as pool:
                    for idx, res in pool.map(_exec_async_json, async_tc):
                        exec_results[idx] = res
            elif len(async_tc) == 1:
                idx, tc = async_tc[0]
                tname, targs = tc['name'], tc['arguments']
                if tname == 'web_search':
                    exec_results[idx] = self._execute_web_search(targs)
                elif tname == 'fetch_webpage':
                    exec_results[idx] = self._execute_fetch_webpage(targs)
                else:  # execute_shell
                    exec_results[idx] = self._tool_executor(tname, **targs)

            # Houdini tool (read-onlybatch / writestringrow) 
            _BATCH_READONLY_JSON = frozenset({
                'get_network_structure', 'get_node_parameters', 'list_children',
                'read_selection', 'search_node_types', 'semantic_search_nodes',
                'find_nodes_by_param', 'get_node_inputs', 'check_errors',
                'search_local_doc', 'get_houdini_node_doc', 'list_skills',
                'get_node_positions', 'list_network_boxes',
                'perf_start_profile', 'perf_stop_and_report',
            })
            readonly_batch_j = [(i, tc) for i, tc in houdini_tc if tc['name'] in _BATCH_READONLY_JSON]
            mutating_calls_j = [(i, tc) for i, tc in houdini_tc if tc['name'] not in _BATCH_READONLY_JSON]

            if len(readonly_batch_j) > 1 and self._batch_tool_executor:
                batch_input = [(tc['name'], tc['arguments']) for _, tc in readonly_batch_j]
                try:
                    batch_results = self._batch_tool_executor(batch_input)
                    for (idx, _), result in zip(readonly_batch_j, batch_results):
                        exec_results[idx] = result
                except Exception as e:
                    _dbg(f"[AI Client] JSON-mode batch execution failed, falling back to serial: {e}")
                    for idx, tc in readonly_batch_j:
                        tname, targs = tc['name'], tc['arguments']
                        try:
                            exec_results[idx] = self._tool_executor(tname, **targs)
                        except Exception as ex:
                            exec_results[idx] = {"success": False, "error": str(ex)}
            else:
                for idx, tc in readonly_batch_j:
                    tname, targs = tc['name'], tc['arguments']
                    if not self._tool_executor:
                        exec_results[idx] = {"success": False, "error": f"toolexecute notset: {tname}"}
                    else:
                        try:
                            exec_results[idx] = self._tool_executor(tname, **targs)
                        except Exception as e:
                            exec_results[idx] = {"success": False, "error": str(e)}

            for idx, tc in mutating_calls_j:
                tname, targs = tc['name'], tc['arguments']
                if not self._tool_executor:
                    exec_results[idx] = {"success": False, "error": f"toolexecute notset: {tname}"}
                else:
                    try:
                        exec_results[idx] = self._tool_executor(tname, **targs)
                    except Exception as e:
                        import traceback
                        exec_results[idx] = {"success": False, "error": f"toolexecuteexception: {str(e)}\n{traceback.format_exc()[:200]}"}

            # statsoneprocessresult
            should_break_limit = False
            for i, tc in enumerate(tool_calls):
                tool_name = tc['name']
                arguments = tc['arguments']
                result = exec_results[i]

                total_tool_calls += 1
                call_signature = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"

                if total_tool_calls > max_tool_calls:
                    _dbg(f"[AI Client] ⚠️ JSON mode: reached max tool-call limit ({max_tool_calls})")
                    should_break_limit = True
                    break

                if call_signature == last_call_signature:
                    consecutive_same_calls += 1
                else:
                    consecutive_same_calls = 1
                    last_call_signature = call_signature

                if on_tool_call:
                    on_tool_call(tool_name, arguments)

                tool_calls_history.append({
                    'tool_name': tool_name,
                    'arguments': arguments,
                    'result': result
                })

                if not result.get('success'):
                    error_detail = result.get('error', 'notknowerror')
                    _dbg(f"[AI Client] ⚠️ Tool execution failed: {tool_name}")
                    _dbg(f"[AI Client]   Error detail: {error_detail[:200]}")

                if on_tool_result:
                    on_tool_result(tool_name, arguments, result)

                compressed = self._compress_tool_result(tool_name, result)
                if result.get('success'):
                    tool_results.append(f"{tool_name}:{compressed}")
                else:
                    tool_results.append(f"{tool_name}:error:{compressed}")

            if should_break_limit:
                return {
                    'ok': True,
                    'content': full_content + f"\n\nalreadyreachtotoolcalltimecountlimit({max_tool_calls}), autostop. ",
                    'tool_calls_history': tool_calls_history,
                    'iterations': iteration
                }
            
            # Minimal format: tool result, continue or summarize.
            # Collect failed-tool details (explicitly call out which tool, what error)
            failed_tool_details = []
            for r in tool_results:
                if ':error:' in r:
                    failed_tool_details.append(r)
            has_failed_tools = len(failed_tool_details) > 0
            # checkwhetherhasnotcomplete todo (viachecktoolcallhistory) 
            has_pending_todos = False
            for tc in tool_calls_history:
                if tc.get('tool_name') == 'add_todo':
                    # ifhasadd_todobutnothasforshould update_todo done, descriptionstillhasnotcomplete task
                    has_pending_todos = True
                    break
            
            # constructhint (withmultiroundthinkingguideimport) 
            think_hint = 'firstin<think>labelwithinanalyzeexecuteresultandcurrentprogress, againdecidefixedbelowonestep. ' if enable_thinking else ''
            
            todo_hint = "Mark completed steps with update_todo. "
            if has_failed_tools:
                # Explicitly list the failed tools and error reasons; avoids the AI
                # incorrectly invoking check_errors when the failure is a tool-layer
                # issue (bad args / execution error), not a Houdini node error.
                fail_summary = '; '.join(failed_tool_details)
                prompt = ('|'.join(tool_results)
                          + f"|⚠️ Some tool calls returned errors (these are tool-layer parameter/execution errors, "
                          + f"NOT Houdini node errors — do not call check_errors; fix the arguments and retry directly): {fail_summary}"
                          + f"|{think_hint}{todo_hint}Fix the arguments based on the error reasons above and resume completing the task. Do not abort just because of failures.")
            elif has_pending_todos and iteration < max_iterations - 2:
                prompt = '|'.join(tool_results) + f"|Pending todos detected. {think_hint}{todo_hint}Please continue."
            elif iteration >= max_iterations - 1:
                prompt = '|'.join(tool_results) + f"|{todo_hint}Please produce the final summary describing what was completed."
            else:
                prompt = '|'.join(tool_results) + f"|{think_hint}{todo_hint}Continue or summarize."
            
            # Use the system role to pass back tool results; avoids mixing with user messages
            # note: partpartmodelnot supportedmulti system message, hereuseclearcertain  [TOOL_RESULT] mark
            # ★ checkwhetherhasviewportscreenshotneedsinject
            _viewport_imgs = []
            if supports_vision:
                for tc in tool_calls:
                    _r = exec_results.get(tool_calls.index(tc))
                    if isinstance(_r, dict) and _r.get('_viewport_image'):
                        _viewport_imgs.append((_r['_viewport_image'], _r.get('_image_media_type', 'image/jpeg')))
            
            if _viewport_imgs:
                # multimodalmessage: text + image
                _content_parts = [{"type": "text", "text": f"[TOOL_RESULT]\n{prompt}\n[viewport snapshot attached — please analyze the current viewport state]"}]
                for _vimg_b64, _vimg_mt in _viewport_imgs:
                    _content_parts.append({"type": "image_url", "image_url": {"url": f"data:{_vimg_mt};base64,{_vimg_b64}"}})
                    _dbg(f"[AI Client] 📸 Viewport screenshot injected (JSON mode, {len(_vimg_b64)//1024}KB)")
                working_messages.append({'role': 'user', 'content': _content_parts})
            else:
                working_messages.append({
                    'role': 'user',
                    'content': f'[TOOL_RESULT]\n{prompt}'
                })
            
            # savecurrentroundtime content (usepre-compilepositivethencleanupXMLlabel) 
            cleaned_round = round_content
            for _pat in self._RE_CLEAN_PATTERNS:
                cleaned_round = _pat.sub('', cleaned_round)
            cleaned_round = re.sub(r'<[^>]+>', '', cleaned_round)  # cleanupallremaining XMLlabel
            # onlyaddnotemptyandnotduplicate content
            if cleaned_round.strip():
                # checkwhetherwithalreadyhascontentduplicate (simplegore: ifcontentfinishallsame, skip) 
                if cleaned_round.strip() not in full_content:
                    full_content += cleaned_round
                else:
                    # ifcontentduplicate, onlyaddonce (avoidmany timesduplicate) 
                    pass
        
        # ifloopendbutcontentasempty, andhastoolcallhistory, forceneedrequestgeneratesummary
        if not full_content.strip() and tool_calls_history:
            _dbg("[AI Client] ⚠️ JSON mode: tool calls done but no reply content, forcing summary generation")
            # lastoncerequest, forceneedrequestsummary
            working_messages.append({
                'role': 'user',
                'content': 'pleasegeneratefinalsummary, descriptioncompleted operationandresult. '
            })
            
            # againtimerequestgeneratesummary
            summary_content = ""
            for chunk in self.chat_stream(
                messages=working_messages,
                model=model,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens or 500,  # limitsummarylength
                tools=None,
                tool_choice=None
            ):
                if chunk.get('type') == 'content':
                    content = chunk.get('content', '')
                    summary_content += content
                    if on_content:
                        on_content(content)
                elif chunk.get('type') == 'done':
                    break
            
            full_content = summary_content if summary_content else full_content
        
        # compute cache commandinrate
        prompt_total = total_usage['cache_hit_tokens'] + total_usage['cache_miss_tokens']
        if prompt_total > 0:
            total_usage['cache_hit_rate'] = total_usage['cache_hit_tokens'] / prompt_total
        else:
            total_usage['cache_hit_rate'] = 0
        
        _result = {
            'ok': True,
            'content': full_content if full_content.strip() else "(toolcallcomplete, butnotgeneratereply)",
            'tool_calls_history': tool_calls_history,
            'call_records': call_records,
            'iterations': iteration,
            'usage': total_usage
        }
        
        # ★ Hook: on_after_response — notifyplugin Agent Loop end
        try:
            from .hooks import get_hook_manager as _ghm
            _ghm().fire('on_after_response',
                       result=_result, model=model, provider=provider)
        except Exception:
            pass
        
        return _result
    
    def agent_loop_auto(self,
                        messages: List[Dict[str, Any]],
                        model: str = 'gpt-5.2',
                        provider: str = 'openai',
                        **kwargs) -> Dict[str, Any]:
        """autoselectmergesuit  Agent Loop mode"""
        if self._supports_function_calling(provider, model):
            return self.agent_loop_stream(messages=messages, model=model, provider=provider, **kwargs)
        else:
            return self.agent_loop_json_mode(messages=messages, model=model, provider=provider, **kwargs)


# compatible witholdcode
OpenAIClient = AIClient
