import pytest

from mil_agent.data import synthetic
from mil_agent.tools.diagnosis_package import classifier


@pytest.mark.parametrize("sample,point", [
    ("A", "Beneficiary bank"), ("C1", "Beneficiary bank"), ("D", "NPCI switch"),
    ("E", "Acquiring bank"), ("F", "Acquiring bank"), ("G", "None"),
])
def test_hero_failure_points(case_at, sample, point):
    d = case_at(sample, "diagnosis").diagnosis
    assert d.failure_point == point and d.confidence >= 0.85 and not d.missing_documents


def test_every_reason_cites_a_timeline_event(case_at):
    c = case_at("A", "diagnosis")
    ids = {e.id for e in c.timeline}
    cited = [r.split("]")[0].lstrip("[") for r in c.diagnosis.reasons]
    assert cited and all(i in ids for i in cited)


def test_case_b_asks_for_the_merchant_record_instead_of_guessing(case_at):
    c = case_at("B", "diagnosis")
    assert c.state == "reconstructed" and c.diagnosis.confidence < classifier.CONFIDENT
    assert "merchant" in c.diagnosis.missing_documents[0].lower()
    assert c.diagnosis.outage and "PaySwift" in c.diagnosis.outage  # declared incident that evening


def test_case_c_is_flagged_as_part_of_the_outage_cluster(case_at):
    d = case_at("C2", "diagnosis").diagnosis
    assert d.cluster_id and d.cluster_id.startswith("CLU-COASTAL")
    assert any("Outage cluster" in r for r in d.reasons)


def test_cluster_detector_finds_only_the_seeded_cluster():
    clusters = synthetic.all_clusters()
    assert len(clusters) == 1 and clusters[0]["beneficiary"] == synthetic.CLUSTER_BANK
    assert clusters[0]["failure_rate"] > 10 * clusters[0]["baseline_rate"]
