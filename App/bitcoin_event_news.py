"""Relaciona os episódios numéricos ao catálogo documental pesquisado manualmente."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from bitcoin_data import sha256


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def associate(events, catalog):
    sources = {source["source_id"]: source for source in catalog["sources"]}
    if len(sources) != len(catalog["sources"]):
        raise ValueError("Identificador duplicado no catálogo de fontes")
    event_map = {event["event_id"]: event for event in events}
    joined, annotations = [], []
    for link in catalog["associations"]:
        if link["event_id"] not in event_map:
            raise ValueError("Associação aponta para evento inexistente")
        event = event_map[link["event_id"]]
        if link["source_id"] and link["source_id"] not in sources:
            raise ValueError("Associação aponta para fonte inexistente")
        source = sources.get(link["source_id"], {})
        incident = source.get("event_time_utc", "")
        peak = datetime.fromisoformat(event["peak_available_at_utc"])
        lag = (peak - datetime.fromisoformat(incident)).total_seconds() / 60 if incident else ""
        joined.append({**link, "peak_available_at_utc": event["peak_available_at_utc"],
                       "return_30m_pct": event["return_30m_pct"], "source_title": source.get("title", ""),
                       "source_url": source.get("url", ""), "publisher": source.get("publisher", ""),
                       "publication_date": source.get("publication_date", ""),
                       "publication_precision": source.get("publication_precision", "unknown"),
                       "published_at_utc": source.get("published_at_utc", ""),
                       "incident_time_utc": incident, "peak_minus_incident_minutes": lag,
                       "causality_identified": False, "ready_for_realtime_training": False})
    for event in events:
        links = [row for row in joined if row["event_id"] == event["event_id"]]
        if not links:
            raise ValueError(f"Evento sem avaliação documental: {event['event_id']}")
        clean = {key: value for key, value in event.items() if key != "news_status"}
        annotations.append({**clean, "source_ids": ";".join(row["source_id"] for row in links if row["source_id"]),
                            "association_types": ";".join(sorted({row["association"] for row in links})),
                            "research_status": "reviewed_unresolved" if all(row["association"] == "unresolved" for row in links) else "reviewed_with_limits",
                            "causality_identified": False})
    return joined, annotations


def timed_incident_returns(context, links):
    """Descreve preços antes/depois de incidente conhecido; não estima contrafactual."""
    output = []
    for link in links:
        if link["association"] != "documented_incident_temporal_overlap":
            continue
        anchor = datetime.fromisoformat(link["incident_time_utc"])
        prices = {row["available_at_utc"]: float(row["close_usdt"]) for row in context if row["event_id"] == link["event_id"]}
        anchor_key = anchor.isoformat().replace("+00:00", "Z")
        if anchor_key not in prices:
            raise ValueError("Incidente sem preço de referência no contexto")
        for minutes in (1, 5, 15, 30):
            before = (anchor - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
            after = (anchor + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
            if before in prices and after in prices:
                output.append({"event_id": link["event_id"], "source_id": link["source_id"],
                               "incident_time_utc": anchor_key, "horizon_minutes": minutes,
                               "pre_return_pct": 100*(prices[anchor_key]/prices[before]-1),
                               "post_return_pct": 100*(prices[after]/prices[anchor_key]-1),
                               "interpretation": "Descritivo, sem controle ou causalidade; notícia posterior ao incidente"})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results" / "bitcoin_events")
    parser.add_argument("--catalog", type=Path, default=Path(__file__).parent / "research" / "bitcoin_news_sources.json")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    events = read_csv(args.results / "research_events.csv")
    joined, annotated = associate(events, catalog)
    write_csv(args.results / "news_sources.csv", catalog["sources"])
    write_csv(args.results / "event_news.csv", joined)
    write_csv(args.results / "events_with_news.csv", annotated)
    timed = timed_incident_returns(read_csv(args.results / "event_context.csv"), joined)
    if timed:
        write_csv(args.results / "timed_incident_returns.csv", timed)
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "catalog_sha256": sha256(args.catalog), "research_events_sha256": sha256(args.results / "research_events.csv"),
               "events_reviewed": len(events), "sources_catalogued": len(catalog["sources"]), "documentary_links": len(joined),
               "events_with_documented_temporal_incident": len({row["event_id"] for row in joined if row["association"] == "documented_incident_temporal_overlap"}),
               "events_with_retrospective_market_mechanism": len({row["event_id"] for row in joined if row["association"] == "retrospective_market_mechanism"}),
               "unresolved_events": [row["event_id"] for row in annotated if row["research_status"] == "reviewed_unresolved"],
               "causality_identified": False, "pearson_news_correlation_estimated": False,
               "note": "Amostra selecionada por extremos, sem corpus independente de notícias e controles. Não estima correlação populacional, efeito causal ou sinal negociável."}
    (args.results / "news_manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(timed, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
