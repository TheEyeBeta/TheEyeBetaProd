#!/usr/bin/env bash
# Generate Python gRPC stubs from libs/zinc_proto/*.proto
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="${REPO_ROOT}/libs/zinc_proto"
OUT_DIR="${PROTO_DIR}/src/zinc_proto"
mkdir -p "${OUT_DIR}"
python -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${OUT_DIR}" \
  --grpc_python_out="${OUT_DIR}" \
  "${PROTO_DIR}/guard.proto" \
  "${PROTO_DIR}/risk.proto" \
  "${PROTO_DIR}/compliance.proto"
# Fix relative imports in generated grpc stub.
if [[ "$(uname -s)" == "Darwin" ]]; then
  sed -i '' 's/^import guard_pb2/from zinc_proto import guard_pb2/' "${OUT_DIR}/guard_pb2_grpc.py"
  sed -i '' 's/^import risk_pb2/from zinc_proto import risk_pb2/' "${OUT_DIR}/risk_pb2_grpc.py"
  sed -i '' 's/^import compliance_pb2/from zinc_proto import compliance_pb2/' "${OUT_DIR}/compliance_pb2_grpc.py"
else
  sed -i 's/^import guard_pb2/from zinc_proto import guard_pb2/' "${OUT_DIR}/guard_pb2_grpc.py"
  sed -i 's/^import risk_pb2/from zinc_proto import risk_pb2/' "${OUT_DIR}/risk_pb2_grpc.py"
  sed -i 's/^import compliance_pb2/from zinc_proto import compliance_pb2/' "${OUT_DIR}/compliance_pb2_grpc.py"
fi
echo "Generated stubs in ${OUT_DIR}"
