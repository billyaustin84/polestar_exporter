"""Keep the example Grafana dashboard in sync with the metrics we export."""

import json
import re
from pathlib import Path

DASHBOARD = Path(__file__).parent.parent / "grafana" / "polestar-dashboard.json"


def exported_metric_names(registry) -> set[str]:
    names = set()
    for family in registry.collect():
        names.add(family.name)
        if family.type == "counter":
            names.add(f"{family.name}_total")
    return names


def test_dashboard_is_valid_json():
    dashboard = json.loads(DASHBOARD.read_text())
    assert dashboard["panels"], "dashboard has no panels"
    assert any(v["name"] == "vin" for v in dashboard["templating"]["list"])


def test_every_dashboard_metric_is_exported(metrics, registry):
    dashboard = json.loads(DASHBOARD.read_text())
    exprs = [
        target.get("expr", "")
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    assert exprs
    referenced = {
        name
        for expr in exprs
        for name in re.findall(r"polestar_[a-z0-9_]+", expr)
    }
    assert referenced, "no polestar_* metrics referenced in dashboard"
    missing = referenced - exported_metric_names(registry)
    assert not missing, f"dashboard references metrics the exporter never defines: {missing}"


def test_all_panels_have_unique_ids():
    dashboard = json.loads(DASHBOARD.read_text())
    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))
