from confluent_kafka.schema_registry.error import SchemaRegistryError

from kafka_path.fault_experiments import (
    KafkaFaultHarness,
    KafkaRecordObservation,
    RebalanceState,
    SchemaOutcome,
    account_offsets,
    classify_registry_error,
    classify_schema_candidate,
    normalized_provenance,
    run_schema_experiment,
)
from kafka_path.settings import KafkaSettings


def test_offset_accounting_is_partition_local_and_exposes_replay():
    result = account_offsets(
        ["a", "b", "c", "d"],
        [
            KafkaRecordObservation("a", 0, 10),
            KafkaRecordObservation("c", 1, 3),
            KafkaRecordObservation("a", 0, 10),
            KafkaRecordObservation("b", 0, 12),
            KafkaRecordObservation("extra", 1, 2),
        ],
    )
    assert result.missing == 1
    assert result.duplicates == 1
    assert result.unexpected == 1
    assert result.offset_replays == 1
    assert result.partition_order_violations == 1
    assert result.offset_gaps == 1
    assert result.delivery_pct == 75.0


def test_empty_and_invalid_expected_sets_are_explicit():
    assert account_offsets([], []).delivery_pct == 100.0
    try:
        account_offsets(["same", "same"], [])
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate expected ids were accepted")


class FakeFaultAdapter:
    def __init__(self):
        self.ids = []
        self.operations = []
        self.state = RebalanceState()
        self.next_offset = 0

    def start(self, group_id):
        self.operations.append(("start", group_id))
        self.state.assigned(1)

    def publish(self, message_id):
        self.operations.append(("publish", message_id))
        self.ids.append(KafkaRecordObservation(message_id, 0, self.next_offset))
        self.next_offset += 1

    def restart_broker(self):
        self.operations.append(("restart_broker",))

    def restart_consumer(self, group_id):
        self.operations.append(("restart_consumer", group_id))
        self.state.revoked()
        self.state.assigned(2)

    def trigger_rebalance(self, group_id):
        self.operations.append(("rebalance", group_id))
        self.state.revoked()
        self.state.assigned(3)

    def observations(self, timeout_s):
        self.operations.append(("observations", timeout_s))
        result, self.ids = self.ids, []
        return result

    def rebalance_state(self):
        return self.state

    def close(self):
        self.operations.append(("close",))


def test_harness_runs_restart_and_rebalance_with_isolated_group_ids():
    adapter = FakeFaultAdapter()
    results = KafkaFaultHarness(adapter, KafkaSettings(), clock=lambda: 10.0).run_all(4)
    assert [item.scenario for item in results] == [
        "broker_restart", "consumer_restart", "consumer_group_rebalance"
    ]
    assert all(item.accounting.delivery_pct == 100 for item in results)
    assert all(not item.timed_out for item in results)
    starts = [operation[1] for operation in adapter.operations if operation[0] == "start"]
    assert len(starts) == len(set(starts)) == 3
    assert adapter.operations[-1] == ("close",)
    assert results[-1].rebalance.generation_changes >= 2


def test_schema_registry_and_evolution_outcomes_are_not_conflated():
    assert classify_registry_error(None) is SchemaOutcome.AVAILABLE
    assert classify_registry_error(
        SchemaRegistryError(503, 50001, "unavailable")
    ) is SchemaOutcome.UNAVAILABLE
    assert classify_schema_candidate(expected_compatible=True, accepted=True) is SchemaOutcome.COMPATIBLE_ACCEPTED
    assert classify_schema_candidate(expected_compatible=True, accepted=False) is SchemaOutcome.COMPATIBLE_REJECTED
    assert classify_schema_candidate(expected_compatible=False, accepted=False) is SchemaOutcome.INCOMPATIBLE_REJECTED
    assert classify_schema_candidate(expected_compatible=False, accepted=True) is SchemaOutcome.INCOMPATIBLE_ACCEPTED


class FakeRegistry:
    def __init__(self, outcomes=(True, False), error=None):
        self.outcomes = iter(outcomes)
        self.error = error
        self.calls = []

    def get_compatibility(self, *, subject_name):
        if self.error:
            raise self.error
        self.calls.append(("policy", subject_name))
        return "BACKWARD_TRANSITIVE"

    def test_compatibility_all_versions(self, subject, candidate, *, normalize):
        self.calls.append((subject, candidate, normalize))
        return next(self.outcomes)


def test_schema_experiment_checks_candidates_without_registration():
    registry = FakeRegistry()
    result = run_schema_experiment(
        registry, subject="vitals-value",
        compatible_candidate="additive", incompatible_candidate="field-type-change",
    )
    assert result.availability is SchemaOutcome.AVAILABLE
    assert result.compatible_candidate is SchemaOutcome.COMPATIBLE_ACCEPTED
    assert result.incompatible_candidate is SchemaOutcome.INCOMPATIBLE_REJECTED
    assert registry.calls == [
        ("policy", "vitals-value"),
        ("vitals-value", "additive", True),
        ("vitals-value", "field-type-change", True),
    ]


def test_schema_experiment_records_registry_outage_without_candidate_claims():
    result = run_schema_experiment(
        FakeRegistry(error=SchemaRegistryError(503, 50001, "unavailable")),
        subject="vitals-value", compatible_candidate=object(), incompatible_candidate=object(),
    )
    assert result.availability is SchemaOutcome.UNAVAILABLE
    assert result.compatible_candidate is None
    assert result.incompatible_candidate is None
    assert "unavailable" in result.error


def test_non_outage_registry_errors_remain_failures():
    error = SchemaRegistryError(404, 40403, "schema missing")
    try:
        classify_registry_error(error)
    except SchemaRegistryError as raised:
        assert raised is error
    else:
        raise AssertionError("unknown schema was misclassified as an outage")


def test_normalized_provenance_is_stable_and_records_semantics():
    first = normalized_provenance(KafkaSettings())
    second = normalized_provenance(KafkaSettings())
    assert first == second
    assert len(first["config_sha256"]) == 64
    assert first["semantics"] == {
        "delivery": "at_least_once",
        "ordering_scope": "partition",
        "commit": "synchronous_after_handler_or_dlq",
    }
    assert first["producer"]["acks"] == "all"
    assert first["consumer"]["enable.auto.commit"] is False
