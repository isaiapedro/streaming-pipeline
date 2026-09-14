import subprocess
import sys

from google.protobuf import descriptor_pb2

from schema import vitals_pb2


def test_checked_in_protobuf_descriptor_matches_canonical_proto(tmp_path):
    """Fail when vitals.proto changes without regenerating vitals_pb2.py."""

    descriptor_path = tmp_path / "vitals.pb"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            "--proto_path=schema/proto",
            f"--descriptor_set_out={descriptor_path}",
            "vitals.proto",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(descriptor_path.read_bytes())
    assert len(descriptor_set.file) == 1
    compiled = descriptor_set.file[0]
    checked_in = descriptor_pb2.FileDescriptorProto.FromString(
        vitals_pb2.DESCRIPTOR.serialized_pb
    )
    # Recent protoc versions materialize inferred JSON names while the
    # checked-in generator omits them. They do not change the protobuf schema,
    # so compare the canonical descriptors without those inferred values.
    for descriptor in (compiled, checked_in):
        for message in descriptor.message_type:
            for field in message.field:
                field.ClearField("json_name")
    assert compiled == checked_in
