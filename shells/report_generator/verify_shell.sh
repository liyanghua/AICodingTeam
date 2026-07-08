#!/bin/bash
# Shell 验证脚本

set -e

echo "=== Shell 验证测试 ==="
echo ""

# 1. 检查文件结构
echo "1. 检查文件结构..."
for file in \
  "shells/report_generator/server/server.js" \
  "shells/report_generator/web/index.html" \
  "shells/report_generator/web/app.js" \
  "shells/report_generator/web/styles.css" \
  "shells/report_generator/engine/rule_engine.py" \
  "shells/report_generator/contract.schema.json" \
  "shells/report_generator/version.txt" \
  "shells/report_generator/README.md"
do
  if [ -f "$file" ]; then
    echo "  ✓ $file"
  else
    echo "  ✗ $file (missing)"
    exit 1
  fi
done
echo ""

# 2. 测试 Python 规则引擎
echo "2. 测试 Python 规则引擎..."
cd shells/report_generator/engine
echo '{"rule_id": "opportunity_score", "inputs": {"market_size": 20, "growth_rate": 20, "competition_intensity": 15, "brand_fit": 15, "supply_chain_feasibility": 15, "differentiation_strength": 15}}' | python3 rule_engine.py > /tmp/rule_test.json
if grep -q '"score": 100' /tmp/rule_test.json; then
  echo "  ✓ 规则引擎正常工作"
else
  echo "  ✗ 规则引擎输出异常"
  cat /tmp/rule_test.json
  exit 1
fi
cd - > /dev/null
echo ""

# 3. 测试 Node.js 语法
echo "3. 检查 server.js 语法..."
node --check shells/report_generator/server/server.js
echo "  ✓ server.js 语法正确"
echo ""

# 4. 准备测试环境
echo "4. 准备测试环境..."
TEST_DIR="/tmp/shell_test_$$"
mkdir -p "$TEST_DIR"
cp shells/report_generator/test_fixture_app.config.json "$TEST_DIR/app.config.json"
mkdir -p "$TEST_DIR/artifacts"
mkdir -p "$TEST_DIR/evidence"
mkdir -p "$TEST_DIR/uploads"
echo "  ✓ 测试目录: $TEST_DIR"
echo ""

# 5. 启动服务器（后台）
echo "5. 启动 Shell Server..."
cd "$TEST_DIR"
PORT=18765
node "$(pwd)/../shells/report_generator/server/server.js" > server.log 2>&1 &
SERVER_PID=$!
cd - > /dev/null
echo "  Server PID: $SERVER_PID"
echo "  等待服务器启动..."
sleep 2
echo ""

# 6. 测试 API 端点
echo "6. 测试 API 端点..."

# Health check
echo "  测试 /api/health..."
curl -s http://localhost:$PORT/api/health | grep -q '"status":"ok"' && echo "  ✓ Health check 正常" || (echo "  ✗ Health check 失败"; kill $SERVER_PID; exit 1)

# Config endpoint
echo "  测试 /api/config..."
curl -s http://localhost:$PORT/api/config | grep -q '"shell_kind":"report_generator"' && echo "  ✓ Config 端点正常" || (echo "  ✗ Config 端点失败"; kill $SERVER_PID; exit 1)

# Nodes endpoint
echo "  测试 /api/nodes..."
curl -s http://localhost:$PORT/api/nodes | grep -q '"id":"form_input"' && echo "  ✓ Nodes 端点正常" || (echo "  ✗ Nodes 端点失败"; kill $SERVER_PID; exit 1)

echo ""

# 7. 测试规则引擎集成
echo "7. 测试节点执行（规则引擎集成）..."
RESULT=$(curl -s -X POST http://localhost:$PORT/api/nodes/opportunity_scoring/run \
  -H "Content-Type: application/json" \
  -d '{
    "market_size": 18,
    "growth_rate": 18,
    "competition_intensity": 12,
    "brand_fit": 12,
    "supply_chain_feasibility": 10,
    "differentiation_strength": 5
  }')

if echo "$RESULT" | grep -q '"status":"ok"'; then
  echo "  ✓ 节点执行成功"
else
  echo "  ✗ 节点执行失败"
  echo "$RESULT"
  kill $SERVER_PID
  exit 1
fi
echo ""

# 8. 清理
echo "8. 清理..."
kill $SERVER_PID 2>/dev/null || true
sleep 1
rm -rf "$TEST_DIR"
echo "  ✓ 清理完成"
echo ""

echo "=== ✅ 所有验证测试通过 ==="
echo ""
echo "Shell 已准备就绪，可以："
echo "  1. 启动服务器: cd <app_dir> && node ../../shells/report_generator/server/server.js"
echo "  2. 浏览器访问: http://localhost:8765"
echo "  3. 查看三栏交互界面"
echo ""