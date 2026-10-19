#!/bin/bash
# ============================================
# DRFX Catalog Deploy Script (v2 — with images)
# ============================================
# วิธีใช้: bash deploy.sh
# Upload: index.html + images/ folder
# ============================================

VPS_IP="78.46.68.197"
VPS_USER="root"
REMOTE_DIR="/var/www/drfx-catalog"
PORT=3001

echo ""
echo "  ██████╗ ██████╗ ███████╗██╗  ██╗"
echo "  ██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝"
echo "  ██║  ██║██████╔╝█████╗   ╚███╔╝ "
echo "  ██║  ██║██╔══██╗██╔══╝   ██╔██╗ "
echo "  ██████╔╝██║  ██║██║     ██╔╝ ██╗"
echo "  ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝"
echo "  DRFX BOT BUILDERS - Deploy Tool v2"
echo ""

# ============================================
# ตรวจไฟล์/โฟลเดอร์ที่จำเป็น
# ============================================
if [ ! -f "index.html" ]; then
  echo "❌ ไม่พบ index.html ใน folder ปัจจุบัน"
  exit 1
fi

if [ ! -d "images" ]; then
  echo "⚠️  ไม่พบโฟลเดอร์ images/ — จะ deploy โดยไม่มีรูป"
  HAS_IMAGES=0
else
  IMAGE_COUNT=$(ls images/ 2>/dev/null | wc -l)
  echo "✓ พบโฟลเดอร์ images/ (${IMAGE_COUNT} ไฟล์)"
  HAS_IMAGES=1
fi

# ============================================
# Deploy
# ============================================
echo ""
echo "[ 1/4 ] สร้าง folder บน VPS..."
ssh ${VPS_USER}@${VPS_IP} "mkdir -p ${REMOTE_DIR}/images"

echo "[ 2/4 ] Upload index.html..."
scp index.html ${VPS_USER}@${VPS_IP}:${REMOTE_DIR}/

if [ "$HAS_IMAGES" = "1" ]; then
  echo "[ 2.5/4 ] Upload images/ (${IMAGE_COUNT} ไฟล์)..."
  scp -r images/* ${VPS_USER}@${VPS_IP}:${REMOTE_DIR}/images/
fi

echo "[ 3/4 ] รัน web server..."
ssh ${VPS_USER}@${VPS_IP} "
  # หยุด server เดิม (ถ้ามี)
  pkill -f 'python3 -m http.server ${PORT}' 2>/dev/null || true
  sleep 1

  # รัน server ใหม่
  cd ${REMOTE_DIR}
  nohup python3 -m http.server ${PORT} > /tmp/drfx-catalog.log 2>&1 &
  echo 'Server started on port ${PORT}'
"

echo "[ 4/4 ] เสร็จแล้ว! ✓"
echo ""
echo "  🌐 URL: http://${VPS_IP}:${PORT}"
echo "  📋 ส่ง URL นี้ให้ลูกค้าได้เลยครับ"
echo ""
echo "  🖼️  ทดสอบรูป: http://${VPS_IP}:${PORT}/images/aegis-x.png"
echo ""