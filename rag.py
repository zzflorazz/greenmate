"""JSON vector index with a keyword-search fallback; no vector database."""
import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile

from embeddings import EMBEDDING_DIM, MODEL_NAME, cosine_sim, get_embedding


KNOWLEDGE_PATH = Path(__file__).resolve().parent / "knowledge" / "plants.json"
_knowledge: list[dict] | None = None
_index: dict | None = None
STOP_WORDS = {"怎么", "如何", "请问", "需要", "是否", "可以", "当前", "植物", "一下", "什么"}
MIN_SIMILARITY = 0.45  # Similarity threshold, not a probability or quality guarantee.


def load_knowledge() -> list[dict]:
    """Read and validate the file; replace the cache only after success."""
    global _knowledge
    records = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    fields = ("name", "light", "water_freq", "tips")
    if not isinstance(records, list):
        raise ValueError("植物知识库必须是 JSON 数组。")
    names = set()
    ids = set()
    for record in records:
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in fields
        ):
            raise ValueError("每条知识必须包含非空字符串 name、light、water_freq、tips。")
        if record["name"] in names:
            raise ValueError("植物名称不能重复。")
        names.add(record["name"])
        # Legacy external fixtures without IDs are accepted for B04 compatibility;
        # maintained plants.json records all carry explicit, stable IDs.
        identifier = record.get('id')
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
                raise ValueError('知识id必须为唯一非空字符串。')
            ids.add(identifier)
    _knowledge = records
    return deepcopy(_knowledge)


def get_knowledge() -> list[dict]:
    if _knowledge is None:
        return load_knowledge()
    return deepcopy(_knowledge)


def _query_terms(query: str) -> set[str]:
    # Chinese has no word separators: overlapping two-character terms provide
    # basic matches such as “浇水” and “积水” without a tokenizer dependency.
    terms = set(re.findall(r"[a-z0-9]+", query))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", query):
        if len(phrase) == 1:
            continue
        terms.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return terms - STOP_WORDS


def _cited(record: dict, query: str) -> dict:
    result = deepcopy(record)
    identifier = record.get('id') or 'plant_' + hashlib.sha256(record['name'].encode()).hexdigest()[:12]
    terms = _query_terms(query.casefold())
    fragments = [record[key] for key in ('temperature', 'humidity', 'light', 'high_temperature_risk', 'tips', 'water_freq')
                 if isinstance(record.get(key), str)]
    hits = [text for text in fragments if any(term in text.casefold() for term in terms)]
    result['citation'] = {'id': identifier, 'name': record['name'], 'snippet': '\n'.join(hits or fragments[:1])}
    return result


def simple_search(query: str, top_n: int = 2) -> list[dict]:
    if not query.strip() or top_n <= 0:
        return []
    query = query.casefold()
    records = get_knowledge()
    # An explicit plant name takes priority over generic words shared by plants.
    named = [record for record in records if record["name"].casefold() in query]
    if named:
        return [_cited(record, query) for record in named[:top_n]]
    terms = _query_terms(query)
    ranked = []
    for record in records:
        text = (record["name"] + " " + record["tips"]).casefold()
        score = sum(term in text for term in terms)
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [_cited(record, query) for _, record in ranked[:top_n]]


def _knowledge_hash(records: list[dict]) -> str:
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _valid_index(index, records: list[dict]) -> bool:
    if not isinstance(index, dict) or (
        index.get("version") != 1 or index.get("model") != MODEL_NAME
        or index.get("knowledge_hash") != _knowledge_hash(records)
    ):
        return False
    items = index.get("items")
    if not isinstance(items, list) or len(items) != len(records):
        return False
    for item, record in zip(items, records):
        if not isinstance(item, dict) or item.get("record") != record:
            return False
        vector = item.get("embedding")
        if not isinstance(vector, list) or len(vector) != EMBEDDING_DIM:
            return False
        if not all(type(value) in (int, float) and math.isfinite(value) for value in vector):
            return False
        if not any(vector):
            return False
    return True


def build_knowledge_index(force: bool = False) -> dict:
    """Reuse a matching index; otherwise encode each entry and atomically save it."""
    global _index
    records = get_knowledge()
    path = KNOWLEDGE_PATH.with_name("index.json")
    if not force:
        if _valid_index(_index, records):
            return _index
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if _valid_index(saved, records):
            _index = saved
            return _index
    items = []
    for record in records:
        text = (
            f"植物：{record['name']}。光照：{record['light']}。"
            f"浇水：{record['water_freq']}。养护建议：{record['tips']}"
            + f" 适宜温度：{record.get('temperature', '')}；湿度：{record.get('humidity', '')}；高温关注：{record.get('high_temperature_risk', '')}"
        )
        items.append({"record": record, "embedding": get_embedding(text)})
    candidate = {"version": 1, "model": MODEL_NAME, "knowledge_hash": _knowledge_hash(records), "items": items}
    if not _valid_index(candidate, records):
        raise ValueError("模型返回了无效向量，索引未更新。")
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as file:
            temporary_path = Path(file.name)
            json.dump(candidate, file, ensure_ascii=False, allow_nan=False)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    _index = candidate
    return _index


def vector_search(query: str, top_n: int = 2) -> list[dict]:
    if not query.strip() or top_n <= 0:
        return []
    try:
        index = build_knowledge_index()
        if not index["items"]:
            return []
        query_vector = get_embedding(query)
        if len(query_vector) != EMBEDDING_DIM or not any(query_vector):
            raise ValueError("查询向量无效。")
        ranked = sorted(
            [(cosine_sim(query_vector, item["embedding"]), item) for item in index["items"]],
            key=lambda pair: pair[0], reverse=True,
        )
        # Respect an explicit plant entity across ALL species; do not let generic
        # Chinese vector similarity substitute another plant's care facts.
        named = [r for r in get_knowledge() if r['name'].casefold() in query.casefold()]
        if named:
            return [_cited(r, query) for r in named[:top_n]]
        return [_cited(item["record"], query) for score, item in ranked if score >= MIN_SIMILARITY][:top_n]
    except Exception as error:
        # Network/model/index failures should not prevent plant-care questions.
        print(f"[rag] 向量检索不可用，回退关键词检索：{type(error).__name__}。")
        return simple_search(query, top_n)
