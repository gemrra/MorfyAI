# -*- coding: utf-8 -*-
"""
Houdini lightweight documentation index system (rewritten version).

Replacement for the old fully-vectorized RAG. Uses a **dict index** to achieve O(1) lookup:
  - node name → document  (from nodes.zip)
  - VEX function → signature + description  (from vex.zip)
  - HOM class/method → signature + description  (from hom.zip)
  - knowledge base → chunked retrieval  (from Doc/*.txt)

Data sources: ZIP files under Houdini's help directory (wiki marker format) + Doc/*.txt knowledge base.
"""

import os
import re
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# ============================================================
# datastructure
# ============================================================

@dataclass
class NodeDoc:
    """nodedocument"""
    node_type: str          # internal name, e.g. "attribwrangle"
    context: str            # sop / dop / obj / cop2 / ...
    title: str              # showname
    description: str        # briefdescription (≤300 chars)
    parameters: list        # [[name, description], ...]  (≤15 item)


@dataclass
class VexDoc:
    """VEX functiondocument"""
    name: str               # functionname
    signature: str          # full signature
    description: str        # briefdescription
    category: str           # partclass, e.g. "attrib", "geo"


@dataclass
class HomDoc:
    """HOM class/methoddocument"""
    name: str               # completename, e.g. "hou.Node"
    doc_type: str           # class / method / function / homclass
    signature: str          # methodsignature
    description: str        # briefdescription


@dataclass
class KnowledgeChunk:
    """knowledgelibrarydocumentsnippet"""
    title: str              # smallsectiontitle
    content: str            # smallsectioncontent (≤2000 chars)
    source: str             # comesourcefilename
    keywords: List[str]     # keywordlist (smallwrite)


# ============================================================
# core: lightweightdocumentindex
# ============================================================

class HoudiniDocIndex:
    """Houdini documentlightweightindex

    use dict realnow O(1) lookup, replacement forallquantityvectorization. 
    indexcomesource: $HFS/houdini/help directorybelow  ZIP file. 
    """

    def __init__(self, help_dir: Optional[str] = None):
        self._help_dir = self._resolve_help_dir(help_dir)

        # three mainindex
        self.node_index: Dict[str, NodeDoc] = {}
        self.vex_index: Dict[str, VexDoc] = {}
        self.hom_index: Dict[str, HomDoc] = {}

        # knowledgelibraryindex
        self.knowledge_chunks: List[KnowledgeChunk] = []

        # helperindex
        self._node_aliases: Dict[str, str] = {}         # alias(smallwrite) → node_type
        self._vex_categories: Dict[str, List[str]] = {}  # category → [func_names]
        self._all_node_types: Optional[set] = None       # lazy initialization

        # cache
        project_root = Path(__file__).parent.parent.parent
        self._cache_dir = project_root / "cache" / "doc_index"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._doc_dir = project_root / "Doc"

        self._load_or_build()
        self._load_knowledge_base()

    # ==========================================================
    # helpdirectorydiscover
    # ==========================================================

    @staticmethod
    def _resolve_help_dir(help_dir: Optional[str]) -> Optional[Path]:
        """autodiscoverdocumentdirectory (containing ZIP file) 

        lookuporderorder: 
        1. explicitly passed in path
        2. Bundled Doc/ directory (ships with the project, ensures it works on any machine)
        3. environmentvariable HFS / hou module
        4. common Windows installpath
        """
        REQUIRED_ZIPS = ("nodes.zip", "vex.zip", "hom.zip")

        def _has_zips(d: Path) -> bool:
            return d.is_dir() and any((d / z).exists() for z in REQUIRED_ZIPS)

        # 0. explicitpath
        if help_dir:
            p = Path(help_dir)
            if _has_zips(p):
                return p

        # 1. bundled with the project Doc/ directory (preferred——ensures cross-machine availability) 
        project_root = Path(__file__).parent.parent.parent
        bundled = project_root / "Doc"
        if _has_zips(bundled):
            return bundled

        # 2. environmentvariable HFS (Houdini standard) 
        hfs = os.environ.get("HFS")
        if hfs:
            p = Path(hfs) / "houdini" / "help"
            if _has_zips(p):
                return p

        # 3. hou moduleget
        try:
            import hou  # type: ignore
            hfs_val = hou.getenv("HFS", "")
            if hfs_val:
                p = Path(hfs_val) / "houdini" / "help"
                if _has_zips(p):
                    return p
        except Exception:
            pass

        # 4. common Windows installpath
        for drive in ("C", "D", "E"):
            base = Path(f"{drive}:/Program Files/Side Effects Software")
            if base.is_dir():
                for v in sorted(base.glob("Houdini*"), reverse=True):
                    p = v / "houdini" / "help"
                    if _has_zips(p):
                        return p

        return None

    # ==========================================================
    # indexload / build / cache
    # ==========================================================

    def _load_or_build(self):
        cache_file = self._cache_dir / "houdini_doc_index.json"

        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("help_dir") == str(self._help_dir) and data.get("version") == 2:
                    self._load_from_cache(data)
                    _dbg(f"[DocIndex] Cache loaded: {len(self.node_index)} nodes, "
                          f"{len(self.vex_index)} VEX, {len(self.hom_index)} HOM")
                    return
            except Exception as e:
                _dbg(f"[DocIndex] Cache load failed: {e}")

        if not self._help_dir:
            _dbg("[DocIndex] Houdini help directory not found, doc index is empty")
            return

        _dbg(f"[DocIndex] Building index: {self._help_dir} ...")
        self._build_indexes()

        try:
            self._save_to_cache(cache_file)
            _dbg(f"[DocIndex] Cached: {len(self.node_index)} nodes, "
                  f"{len(self.vex_index)} VEX, {len(self.hom_index)} HOM")
        except Exception as e:
            _dbg(f"[DocIndex] Cache save failed: {e}")

    def _build_indexes(self):
        """from ZIP filebuildallindex"""
        for name, builder in [("nodes.zip", self._build_node_index),
                               ("vex.zip",   self._build_vex_index),
                               ("hom.zip",   self._build_hom_index)]:
            zp = self._help_dir / name
            if zp.exists():
                _dbg(f"[DocIndex]   Parsing {name} ...")
                builder(zp)
        self._build_aliases()

    # ==========================================================
    # knowledgelibraryload (Doc/*.txt file) 
    # ==========================================================

    def _load_knowledge_base(self):
        """from Doc/ directoryrecursiveload .txt knowledgelibraryfile, by ## titlechunked

        improved:
        1. recursiveloadsubdirectory Doc/**/*.txt
        2. knowledgelibrarycache: willparseresultordercolumnizationto JSON cache
        3. incrementaldetect: byfilemodifywhenbetweendecidebreakwhetherneedsrenewparse
        """
        if not self._doc_dir or not self._doc_dir.is_dir():
            return

        # recursivediscoverall .txt file
        txt_files = sorted(self._doc_dir.rglob("*.txt"))
        if not txt_files:
            return

        kb_cache_file = self._cache_dir / "knowledge_base_cache.json"

        # buildfilefingerprint {relative path: mtime}
        file_fingerprints = {}
        for txt_path in txt_files:
            rel = txt_path.relative_to(self._doc_dir)
            file_fingerprints[str(rel)] = txt_path.stat().st_mtime

        # tryincrementalloadcache
        if kb_cache_file.exists():
            try:
                with open(kb_cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                cached_fingerprints = cache_data.get("fingerprints", {})
                # comparefingerprint: finishallconsistentthendirectlyloadcache
                if cached_fingerprints == file_fingerprints:
                    for chunk_data in cache_data.get("chunks", []):
                        self.knowledge_chunks.append(KnowledgeChunk(
                            title=chunk_data["title"],
                            content=chunk_data["content"],
                            source=chunk_data["source"],
                            keywords=chunk_data["keywords"],
                        ))
                    _dbg(f"[DocIndex] Knowledge base cache loaded: {len(self.knowledge_chunks)} fragment(s) "
                          f"(from {len(txt_files)} file(s))")
                    return
                else:
                    _dbg(f"[DocIndex] Knowledge base files changed, re-parsing...")
            except Exception as e:
                _dbg(f"[DocIndex] Knowledge base cache read failed: {e}")

        # allquantityparse
        for txt_path in txt_files:
            try:
                text = txt_path.read_text(encoding="utf-8")
                # userelative pathas source (keepsubdirectoryinfo) 
                rel = txt_path.relative_to(self._doc_dir)
                source = str(rel.with_suffix("")).replace("\\", "/")
                chunks = self._parse_txt_sections(text, source)
                self.knowledge_chunks.extend(chunks)
            except Exception as e:
                _dbg(f"[DocIndex] Failed to read knowledge file {txt_path.name}: {e}")

        if self.knowledge_chunks:
            _dbg(f"[DocIndex] Knowledge base loaded: {len(self.knowledge_chunks)} fragment(s) "
                  f"(from {len(txt_files)} file(s))")

            # savecache
            try:
                cache_data = {
                    "fingerprints": file_fingerprints,
                    "chunks": [
                        {
                            "title": c.title,
                            "content": c.content,
                            "source": c.source,
                            "keywords": c.keywords,
                        }
                        for c in self.knowledge_chunks
                    ],
                }
                with open(kb_cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, separators=(",", ":"))
                _dbg(f"[DocIndex] Knowledge base cache saved")
            except Exception as e:
                _dbg(f"[DocIndex] Knowledge base cache save failed: {e}")

    @staticmethod
    def _parse_txt_sections(text: str, source: str) -> List[KnowledgeChunk]:
        """will .txt fileby ## titlechunked

        eachby ## start rowasonenewparagraph title. 
        paragraphcontentkeep at most 2000 character. 
        """
        chunks: List[KnowledgeChunk] = []
        current_title = ""
        current_lines: List[str] = []

        def _flush():
            if current_title and current_lines:
                content = '\n'.join(current_lines).strip()
                if len(content) > 30:  # skip very short paragraphs
                    # extractkeyword: English identifier + inChinese phrase
                    keywords_en = [w.lower() for w in
                                   re.findall(r'[a-zA-Z_@][a-zA-Z0-9_@.]*', current_title + ' ' + content)
                                   if len(w) >= 2]
                    keywords_cn = re.findall(r'[\u4e00-\u9fff]{2,}', current_title)
                    all_kw = list(set(keywords_en + keywords_cn))
                    chunks.append(KnowledgeChunk(
                        title=current_title,
                        content=content[:2000],
                        source=source,
                        keywords=all_kw[:50],  # at most50keyword
                    ))

        for line in text.split('\n'):
            # match "## title" (second-leveltitle)
            m = re.match(r'^##\s+(.+)', line)
            if m:
                title_text = m.group(1).strip()
                # skipdecorative separator (such as "## ========" or "## ------")
                if re.match(r'^[=\-#*~]{3,}$', title_text):
                    continue
                _flush()
                current_title = title_text
                current_lines = []
            else:
                current_lines.append(line)

        _flush()
        return chunks

    def search_knowledge(self, query: str, top_k: int = 3) -> List[dict]:
        """inknowledgelibraryinsearchwithquerymatch snippet"""
        if not self.knowledge_chunks:
            return []

        ql = query.lower()
        # extractqueryin keyword
        query_words = set(re.findall(r'[a-zA-Z_@][a-zA-Z0-9_@.]*', ql))
        query_cn = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))

        scored: List[tuple] = []
        for chunk in self.knowledge_chunks:
            score = 0.0
            # English keyword match
            chunk_kw_set = set(chunk.keywords)
            matched = query_words & chunk_kw_set
            score += len(matched) * 0.3
            # intextkeywordmatch
            for cn in query_cn:
                if cn in chunk.title or cn in chunk.content[:200]:
                    score += 0.5
            # exact substringmatch (title) 
            for w in query_words:
                if len(w) >= 3 and w in chunk.title.lower():
                    score += 0.8
            if score > 0.2:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            # cutfetchcontentsummary
            snippet = chunk.content[:300]
            if len(chunk.content) > 300:
                snippet += "..."
            results.append({
                "type": "knowledge",
                "name": chunk.title,
                "snippet": f"[knowledgelibrary] {chunk.title}\n{snippet}",
                "score": min(score, 1.0),
                "source": chunk.source,
            })
        return results

    # --- cacheordercolumnization ---

    def _save_to_cache(self, path: Path):
        data = {
            "help_dir": str(self._help_dir),
            "version": 2,
            "nodes": {
                k: {"node_type": v.node_type, "context": v.context,
                     "title": v.title, "description": v.description,
                     "parameters": v.parameters}
                for k, v in self.node_index.items() if "/" not in k
            },
            "vex": {
                k: {"name": v.name, "signature": v.signature,
                     "description": v.description, "category": v.category}
                for k, v in self.vex_index.items()
            },
            "hom": {
                k: {"name": v.name, "doc_type": v.doc_type,
                     "signature": v.signature, "description": v.description}
                for k, v in self.hom_index.items()
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    def _load_from_cache(self, data: dict):
        for k, v in data.get("nodes", {}).items():
            doc = NodeDoc(**v)
            self.node_index[k] = doc
            if v.get("context"):
                self.node_index[f"{v['context']}/{k}"] = doc

        for k, v in data.get("vex", {}).items():
            self.vex_index[k] = VexDoc(**v)
            if v.get("category"):
                self._vex_categories.setdefault(v["category"], []).append(k)

        for k, v in data.get("hom", {}).items():
            self.hom_index[k] = HomDoc(**v)

        self._build_aliases()

    # ==========================================================
    # Wiki formatparse 
    # ==========================================================

    @staticmethod
    def _parse_wiki(text: str) -> dict:
        """parse Houdini wiki marker formatdocument

        format summary::

            = Title =
            #type: homclass
            #context: sop
            #internal: nodename

            \\"\\"\\"Brief description\\"\\"\\"

            Body text ...

            @parameters
            Param Name:
                Description

            @methods
            ::`methodName(args)`:
                Description
        """
        doc: Dict[str, Any] = {
            "title": "", "type": "", "context": "", "internal": "",
            "description": "", "body": "", "sections": {},
        }

        lines = text.split("\n")
        i, n = 0, len(lines)

        # skipemptyrow
        while i < n and not lines[i].strip():
            i += 1

        # = Title =
        if i < n:
            m = re.match(r"^=\s+(.+?)\s+=\s*$", lines[i])
            if m:
                doc["title"] = m.group(1).strip()
                i += 1

        # #key: value metadatadata
        while i < n:
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            m = re.match(r"^#(\w+):\s*(.*)", line)
            if m:
                key, val = m.group(1).lower(), m.group(2).strip()
                if key in doc:
                    doc[key] = val
                i += 1
            else:
                break

        # """description"""
        while i < n and not lines[i].strip():
            i += 1
        if i < n and lines[i].strip().startswith('"""'):
            dl = lines[i].strip()
            if dl.endswith('"""') and len(dl) > 6:
                doc["description"] = dl[3:-3].strip()
                i += 1
            else:
                parts = [dl[3:]]
                i += 1
                while i < n:
                    if '"""' in lines[i]:
                        parts.append(lines[i].split('"""')[0])
                        i += 1
                        break
                    parts.append(lines[i])
                    i += 1
                doc["description"] = "\n".join(parts).strip()

        # Body + @sections
        cur_sec = "_body"
        buf: List[str] = []
        while i < n:
            line = lines[i]
            s = line.strip()
            if s.startswith("@") and len(s) > 1 and s[1:].split()[0].isalpha():
                # saveprevious paragraph
                text_block = "\n".join(buf).strip()
                if text_block:
                    if cur_sec == "_body":
                        doc["body"] = text_block
                    else:
                        doc["sections"][cur_sec] = text_block
                cur_sec = s[1:].split()[0]
                buf = []
            else:
                buf.append(line)
            i += 1

        text_block = "\n".join(buf).strip()
        if text_block:
            if cur_sec == "_body":
                doc["body"] = text_block
            else:
                doc["sections"][cur_sec] = text_block

        return doc

    # ==========================================================
    # nodeindex  (nodes.zip)
    # ==========================================================

    def _build_node_index(self, zip_path: Path):
        count = 0
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith(".txt") or "/_" in name or name.startswith("_"):
                        continue
                    try:
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        doc = self._parse_wiki(raw)

                        internal = doc.get("internal", "")
                        context = doc.get("context", "")
                        if not internal:
                            parts = name.replace("\\", "/").split("/")
                            internal = Path(parts[-1]).stem
                            if not context and len(parts) >= 3:
                                context = parts[-2] if parts[-2] != "nodes" else ""
                        if not internal:
                            continue

                        params = self._parse_parameters(
                            doc.get("sections", {}).get("parameters", "")
                        )

                        nd = NodeDoc(
                            node_type=internal,
                            context=context,
                            title=doc.get("title", internal),
                            description=doc.get("description", "")[:300],
                            parameters=params[:15],
                        )
                        # short name(nocontextprefix)preferred SOP > OBJ > DOP > other
                        _CTX_PRIORITY = {"sop": 0, "obj": 1, "dop": 2, "cop2": 3}
                        existing = self.node_index.get(internal)
                        if existing is None or (
                            _CTX_PRIORITY.get(context, 99) <
                            _CTX_PRIORITY.get(existing.context, 99)
                        ):
                            self.node_index[internal] = nd
                        if context:
                            self.node_index[f"{context}/{internal}"] = nd
                        count += 1
                    except Exception:
                        continue
        except Exception as e:
            _dbg(f"[DocIndex] nodes.zip failed: {e}")
        _dbg(f"[DocIndex]   -> {count} node docs")

    # ==========================================================
    # VEX index  (vex.zip)
    # ==========================================================

    def _build_vex_index(self, zip_path: Path):
        count = 0
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith(".txt") or "/_" in name:
                        continue
                    try:
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        doc = self._parse_wiki(raw)
                        func_name = doc.get("internal", "") or Path(name).stem
                        if not func_name or func_name.startswith("_"):
                            continue

                        # from body / usage section extractsignature
                        sig_src = (doc.get("body", "") + "\n"
                                   + doc.get("sections", {}).get("usage", ""))
                        sig = ""
                        sig_m = re.search(r"`([^`]+)`", sig_src)
                        if sig_m:
                            sig = sig_m.group(1)

                        parts = name.replace("\\", "/").split("/")
                        cat = parts[-2] if len(parts) >= 2 and parts[-2] != "vex" else ""

                        self.vex_index[func_name] = VexDoc(
                            name=func_name,
                            signature=sig[:200],
                            description=doc.get("description", "")[:200],
                            category=cat,
                        )
                        if cat:
                            self._vex_categories.setdefault(cat, []).append(func_name)
                        count += 1
                    except Exception:
                        continue
        except Exception as e:
            _dbg(f"[DocIndex] vex.zip failed: {e}")
        _dbg(f"[DocIndex]   → {count} VEX functions")

    # ==========================================================
    # HOM index  (hom.zip)
    # ==========================================================

    def _build_hom_index(self, zip_path: Path):
        count = 0
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith(".txt") or "/_" in name:
                        continue
                    try:
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        doc = self._parse_wiki(raw)
                        title = doc.get("title", "")
                        if not title:
                            title = "hou." + Path(name).stem

                        # main entry
                        self.hom_index[title] = HomDoc(
                            name=title,
                            doc_type=doc.get("type", "") or "class",
                            signature="",
                            description=doc.get("description", "")[:300],
                        )
                        count += 1

                        # extractmethod
                        methods_text = doc.get("sections", {}).get("methods", "")
                        if methods_text:
                            count += self._extract_hom_methods(title, methods_text)
                    except Exception:
                        continue
        except Exception as e:
            _dbg(f"[DocIndex] hom.zip failed: {e}")
        _dbg(f"[DocIndex]   → {count} HOM entries")

    def _extract_hom_methods(self, parent: str, text: str) -> int:
        """from @methods section extractmethodsignature"""
        count = 0
        # match  ::`methodName(self, arg1, arg2)`:  orclasssimilarformat
        for m in re.finditer(r"::`(\w+)\(([^)]*)\)`\s*:", text):
            mname = m.group(1)
            margs = m.group(2)
            full = f"{parent}.{mname}"

            # Take the immediately-following indented lines as the description
            pos = m.end()
            desc_lines = []
            for line in text[pos:].split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if line.startswith("    ") or line.startswith("\t"):
                    desc_lines.append(stripped)
                    if len(desc_lines) >= 2:
                        break
                else:
                    break  # notindentationrow = descriptionend

            self.hom_index[full] = HomDoc(
                name=full,
                doc_type="method",
                signature=f"{mname}({margs})",
                description=" ".join(desc_lines)[:200],
            )
            count += 1
        return count

    # ==========================================================
    # parameterparse
    # ==========================================================

    @staticmethod
    def _parse_parameters(text: str) -> list:
        """parse @parameters paragraph → [[name, desc], ...]"""
        params: list = []
        if not text:
            return params
        cur_name = ""
        cur_desc: List[str] = []
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            # skip wiki include refercommand
            if s.startswith(":include") or s.startswith("#include"):
                continue
            if s.endswith(":") and not line.startswith((" ", "\t")):
                if cur_name and not cur_name.startswith(":"):
                    params.append([cur_name, " ".join(cur_desc)[:150]])
                cur_name = s[:-1].strip()
                cur_desc = []
            elif cur_name and (line.startswith("    ") or line.startswith("\t")):
                cur_desc.append(s)
        if cur_name and not cur_name.startswith(":"):
            params.append([cur_name, " ".join(cur_desc)[:150]])
        return params

    # ==========================================================
    # helperindex
    # ==========================================================

    def _build_aliases(self):
        """buildalias (used forfuzzymatch) """
        self._node_aliases.clear()
        for ntype, doc in self.node_index.items():
            if "/" in ntype:
                continue
            low_title = doc.title.lower().replace(" ", "")
            self._node_aliases[low_title] = ntype
            self._node_aliases[ntype.lower()] = ntype
        self._all_node_types = {k for k in self.node_index if "/" not in k}

    # ==========================================================
    # query API
    # ==========================================================

    def lookup_node(self, node_type: str) -> Optional[NodeDoc]:
        """exact lookupnode"""
        doc = self.node_index.get(node_type)
        if doc:
            return doc
        alias = self._node_aliases.get(node_type.lower().replace(" ", ""))
        return self.node_index.get(alias) if alias else None

    def lookup_vex(self, func_name: str) -> Optional[VexDoc]:
        """exact lookup VEX function"""
        return self.vex_index.get(func_name) or self.vex_index.get(func_name.lower())

    def lookup_hom(self, name: str) -> Optional[HomDoc]:
        """exact lookup HOM class/method"""
        return self.hom_index.get(name)

    def search(self, query: str, top_k: int = 5, **_kw) -> List[dict]:
        """multistrategysearch
        
        Returns:
            [{"type": "node"/"vex"/"hom", "name": str,
              "snippet": str, "score": float}, ...]
        """
        results: List[dict] = []
        ql = query.lower().strip()

        # --- finecertainmatch ---
        node = self.lookup_node(ql)
        if node:
            results.append({"type": "node", "name": node.node_type,
                            "snippet": self._fmt_node(node), "score": 1.0})
        vex = self.lookup_vex(ql)
        if vex:
            results.append({"type": "vex", "name": vex.name,
                            "snippet": self._fmt_vex(vex), "score": 1.0})
        hom = self.lookup_hom(query)
        if hom:
            results.append({"type": "hom", "name": hom.name,
                            "snippet": self._fmt_hom(hom), "score": 1.0})

        # --- substringmatch ---
        if len(results) < top_k:
            words = {w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", ql)}
            seen = {r["name"] for r in results}

            for w in words:
                if len(results) >= top_k:
                    break
                for ntype in (self._all_node_types or set()):
                    if w in ntype.lower() and ntype not in seen:
                        d = self.node_index[ntype]
                        results.append({"type": "node", "name": ntype,
                                        "snippet": self._fmt_node(d), "score": 0.5})
                        seen.add(ntype)
                        if len(results) >= top_k:
                            break
                for fname, d in self.vex_index.items():
                    if w in fname.lower() and fname not in seen:
                        results.append({"type": "vex", "name": fname,
                                        "snippet": self._fmt_vex(d), "score": 0.4})
                        seen.add(fname)
                        if len(results) >= top_k:
                            break
                for hname, d in self.hom_index.items():
                    if w in hname.lower() and hname not in seen:
                        results.append({"type": "hom", "name": hname,
                                        "snippet": self._fmt_hom(d), "score": 0.4})
                        seen.add(hname)
                        if len(results) >= top_k:
                                    break

        # --- knowledgelibrarymatch ---
        if len(results) < top_k:
            kb_results = self.search_knowledge(query, top_k=top_k - len(results))
            seen = {r["name"] for r in results}
            for kr in kb_results:
                if kr["name"] not in seen:
                    results.append(kr)
                    seen.add(kr["name"])

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    # ==========================================================
    # autosearch (for _run_agent injectcontext) 
    # ==========================================================

    # common English word (notshouldmatchnode/functionname) 
    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "about",
        "after", "before", "between", "under", "above", "up", "down", "out",
        "off", "over", "then", "than", "so", "no", "not", "only", "very",
        "just", "that", "this", "but", "and", "or", "if", "it", "its",
        "all", "each", "every", "both", "few", "more", "most", "some", "any",
        "how", "what", "which", "who", "when", "where", "why",
        "i", "you", "he", "she", "we", "they", "me", "him", "her", "us",
        "my", "your", "his", "our", "their",
        "new", "use", "get", "set", "run", "add", "create", "make", "node",
        "want", "need", "try", "like", "also", "now", "one", "two",
        "using", "used", "function", "point", "points", "value", "values",
        "type", "name", "input", "output", "result", "data", "file",
        "string", "int", "float", "vector", "matrix", "array", "list",
        "true", "false", "none", "null", "self", "return",
    })

    def auto_retrieve(self, user_message: str, max_chars: int = 1200) -> str:
        """fromusermessageinautoextractkeywordandsearchrelateddocument

        returna compactdocumentsnippet, used forinject AI context. 
        Design principle: quality over quantity — inject at most ~300 tokens per call.
        """
        if not any((self.node_index, self.vex_index, self.hom_index)):
            return ""

        snippets: List[str] = []
        seen: set = set()
        total = 0

        def _add(s: str, key: str):
            nonlocal total
            if key in seen or total + len(s) > max_chars:
                return
            seen.add(key)
            snippets.append(s)
            total += len(s)

        # 1) hou.XXX reference
        for ref in re.findall(r"hou\.([a-zA-Z_][a-zA-Z0-9_.]*)", user_message):
            full = f"hou.{ref}"
            doc = self.lookup_hom(full)
            if doc:
                _add(self._fmt_hom(doc), full)

        # 2) extractEnglish word (ASCII-only, avoid \w matchintext) 
        words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", user_message))
        for w in words:
            wl = w.lower()
            if wl in self._STOP_WORDS or len(wl) < 3:
                continue
            # VEX function
            vdoc = self.vex_index.get(wl) or self.vex_index.get(w)
            if vdoc:
                _add(self._fmt_vex(vdoc), vdoc.name)
            # node
            ndoc = self.node_index.get(wl) or self.node_index.get(w)
            if ndoc:
                _add(self._fmt_node(ndoc), ndoc.node_type)

        # 3) intextkeyword → matchnodetitle
        for kw in re.findall(r"[\u4e00-\u9fff]{2,}", user_message)[:3]:
            for ntype, ndoc in self.node_index.items():
                if "/" in ntype:
                    continue
                if kw in ndoc.title or kw in ndoc.description:
                    _add(self._fmt_node(ndoc), ndoc.node_type)
                    break

        # 4) Knowledge-base match — inject when the query involves a covered topic
        if self.knowledge_chunks:
            _KB_HINTS = {
                # VEX / Wrangle
                "attribute", "attribute", "vex", "@P", "@N", "@Cd", "pscale", "orient",
                "snippet", "code", "function", "syntax", "wrangle", "noise", "noise",
                "copy", "scatter", "color", "normal", "position", "run over",
                "nearpoint", "pcfind", "addpoint", "setpointattrib",
                "hou.", "python", "tableexpression", "hscript", "variable",
                # Heightfields / Terrain
                "heightfield", "terrain", "terrain", "height", "erosion", "erosion",
                "mask", "mask", "layer", "layer",
                # Copernicus / COP
                "copernicus", "cop", "image", "image", "texture", "texture",
                "composite", "composite", "filter", "filter", "gpu",
                # MPM
                "mpm", "physics", "simulation", "simulation", "solver", "solver",
                "snow", "snow", "soil", "mud", "mud", "concrete", "concrete",
                "rubber", "rubber", "jello", "sand", "sand",
                # Machine Learning
                "machine learning", "ml", "machine learning", "train", "training",
                "inference", "inference", "model", "dataset", "dataset", "onnx",
                # Labs
                "labs", "sidefx labs", "game", "game", "gamedev",
                "baker", "bake", "bake", "lod", "impostor", "flowmap",
                "osm", "photogrammetry", "photogrammetry", "wfc", "wave function",
                "tree", "pivot painter", "unreal", "fbx",
                "trim texture", "triplanar", "texel", "mesh slice",
                "destruction", "niagara", "wang tile",
            }
            msg_lower = user_message.lower()
            if any(h in msg_lower for h in _KB_HINTS):
                kb_results = self.search_knowledge(user_message, top_k=2)
                for kr in kb_results:
                    if kr["score"] > 0.3:
                        _add(kr["snippet"], kr["name"])

        if not snippets:
            return ""
        return "[Houdini documentreference]\n" + "\n".join(snippets)

    # ==========================================================
    # Labs directorygenerate (for system prompt inject) 
    # ==========================================================

    _labs_catalog_cache: Optional[str] = None

    def get_labs_catalog(self) -> str:
        """generatecompact  Labs nodedirectory, forinject system prompt

        from labs_knowledge_base   chunk titleinextractnodename, 
        byfeaturepartclassoutput, approximately 2000~3000 character. 
        """
        if self._labs_catalog_cache is not None:
            return self._labs_catalog_cache

        labs_chunks = [c for c in self.knowledge_chunks
                       if c.source == 'labs_knowledge_base']
        if not labs_chunks:
            self._labs_catalog_cache = ""
            return ""

        # extractnodename + briefdescription
        nodes = []
        for chunk in labs_chunks:
            name = chunk.title.strip()
            # godrop "geometry node", "render node" etc.suffix
            name = re.sub(
                r'(geometry|render|object|compositing|sop|cop|top|rop|lop|dop|vop)\s*node\s*$',
                '', name, flags=re.IGNORECASE
            ).strip()
            # godropversionnumber such as 6.0, 1.0
            name = re.sub(r'\d+\.\d+$', '', name).strip()
            # briefdescription (fetch content previous 60 character) 
            desc = chunk.content[:80].split('\n')[0].strip()
            if len(desc) > 60:
                desc = desc[:60] + '...'
            nodes.append((name, desc))

        if not nodes:
            self._labs_catalog_cache = ""
            return ""

        # Categorize by function
        categories: Dict[str, List[str]] = {
            'Game Dev/Optimization': [], 'Texture/UV': [], 'Terrain': [],
            'Photogrammetry': [], 'Procedural Generation': [], 'Modeling/Geometry': [],
            'FX/Visual': [], 'Import/Export': [], 'Flowmap': [],
            'Tree Generation': [], 'Utility': [],
        }

        for name, desc in nodes:
            nl = name.lower()
            dl = desc.lower()
            c = nl + ' ' + dl
            if 'av ' in nl or 'alicevision' in dl or 'photogramm' in dl:
                categories['Photogrammetry'].append(name)
            elif 'flowmap' in nl:
                categories['Flowmap'].append(name)
            elif 'tree' in nl and any(w in nl for w in ('branch', 'trunk', 'leaf', 'controller', 'simple leaf')):
                categories['Tree Generation'].append(name)
            elif any(w in c for w in ('game', 'lod', 'baker', 'bake', 'pivot painter',
                                       'impostor', 'niagara', 'unreal', 'fbx archive')):
                categories['Game Dev/Optimization'].append(name)
            elif any(w in c for w in ('texture', 'texel', 'trim', 'uv ', 'material',
                                       'triplanar', 'normal', 'detail mesh')):
                categories['Texture/UV'].append(name)
            elif any(w in c for w in ('terrain', 'height', 'slope', 'hf ')):
                categories['Terrain'].append(name)
            elif any(w in c for w in ('wfc', 'wave function', 'lightning', 'superformula',
                                       'wang tile', 'sci-fi', 'scifi')):
                categories['Procedural Generation'].append(name)
            elif any(w in c for w in ('mesh', 'edge', 'dissolve', 'thicken', 'border',
                                       'partition', 'skeleton', 'path deform', 'group',
                                       'poly', 'deform', 'resample', 'inside face')):
                categories['Modeling/Geometry'].append(name)
            elif any(w in c for w in ('destruction', 'color', 'shader', 'pbr', 'toon',
                                       'physics', 'fracture', 'pyro', 'rbd', 'smoke')):
                categories['FX/Visual'].append(name)
            elif any(w in c for w in ('export', 'import', 'osm', 'csv', 'xyz', 'goz',
                                       'obj import', 'substance', 'marmoset', 'vector field',
                                       'volume', 'sketchfab', 'pdg')):
                categories['Import/Export'].append(name)
            else:
                categories['Utility'].append(name)

        # Generate compact text
        lines = [f"SideFX Labs Available Nodes ({len(nodes)}) - MUST use search_local_doc before using any:"]
        for cat, items in categories.items():
            if not items:
                continue
            # gore
            unique = sorted(set(items))
            lines.append(f"  [{cat}] {', '.join(unique)}")

        catalog = '\n'.join(lines)
        self._labs_catalog_cache = catalog
        return catalog

    # --- formatization ---

    @staticmethod
    def _fmt_node(d: NodeDoc) -> str:
        s = f"[doc] {d.title} ({d.context}/{d.node_type})"
        if d.description:
            s += f": {d.description[:120]}"
        if d.parameters:
            names = ", ".join(p[0] for p in d.parameters[:6])
            s += f"\n   Params: {names}"
        return s

    @staticmethod
    def _fmt_vex(d: VexDoc) -> str:
        s = f"[VEX] {d.name}"
        if d.signature:
            s += f": {d.signature}"
        elif d.description:
            s += f": {d.description[:120]}"
        return s

    @staticmethod
    def _fmt_hom(d: HomDoc) -> str:
        s = f"[HOM] {d.name}"
        if d.signature:
            s += f" -> {d.signature}"
        if d.description:
            s += f": {d.description[:120]}"
        return s


# ============================================================
# globalsingleexample
# ============================================================

_index_instance: Optional[HoudiniDocIndex] = None


def get_doc_index(help_dir: Optional[str] = None) -> HoudiniDocIndex:
    """getglobaldocumentindexinstance (singleexample) """
    global _index_instance
    if _index_instance is None:
        _index_instance = HoudiniDocIndex(help_dir)
    return _index_instance


# compatible withold API (client.py in  from ..doc_rag import get_doc_rag) 
get_doc_rag = get_doc_index
