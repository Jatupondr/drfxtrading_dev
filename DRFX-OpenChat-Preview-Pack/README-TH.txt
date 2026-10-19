DRFX OpenChat Preview Pack
============================

เป้าหมาย
- URL เดียวต่อ EA
- LINE/OpenChat สามารถอ่าน Open Graph แล้วแสดงรูป Preview ของ EA
- หน้าแต่ละ EA สร้างจาก eas.json รวม 13 ตัว

ติดตั้ง
1) อัปโหลดโฟลเดอร์ ea/ ไปที่ public root ของ drfxtrading.net
2) นำรูป EA จริงใส่โฟลเดอร์ images/ โดยใช้ชื่อไฟล์ตาม IMAGE_FILES.txt
3) ต้องเปิด URL รูปจากอินเทอร์เน็ตได้โดยไม่ Login/Redirect
4) ทดสอบ URL เช่น:
   https://drfxtrading.net/ea/phantom-x/
5) ให้บอท OpenChat ส่ง URL ของ EA เพียง URL เดียวในข้อความที่ต้องการ Preview

สำคัญ
- ไฟล์ชุดนี้ไม่ได้รวมรูปต้นฉบับ เพราะรูปไม่ได้อยู่ในไฟล์ eas.json ที่กู้คืนมา
- หากเว็บเดิมใช้ Next.js/React/ระบบ routing อื่น ให้ผู้พัฒนานำ meta tags ชุดเดียวกันไปใส่ใน route จริง
- หลีกเลี่ยงการทำหน้า Preview ด้วย client-side JavaScript อย่างเดียว; og:* ควรอยู่ใน HTML ที่ server ส่งกลับทันที


UPDATE v4: เพิ่มวิดีโอ YouTube วิธีติดตั้ง DRFX EA บน MT5 ในหน้า EA ทั้ง 12 ตัว
YouTube: https://youtu.be/6wdUT7Za3YQ

UPDATE v6: เพิ่ม DRFX BREAK HUNTER v1.01 เป็น EA ตัวที่ 13
- หน้าใหม่: ea/break-hunter/index.html
- รวมรูปใหม่: images/break-hunter.png (อัปโหลดไปที่ public root พร้อมหน้า EA)
- หน้า EA เดิม 12 หน้าและลิงก์เดิมคงเดิมทั้งหมด
- หน้าใหม่มีปุ่มดาวน์โหลด วิดีโอติดตั้ง และปุ่มดู EA ตัวอื่นทั้งหมด
- ต้องอัปโหลดไฟล์ขึ้นเว็บก่อน URL หน้าใหม่และ OG Preview จะใช้งานได้
- ทุนแนะนำ เงินฝากขั้นต่ำ และระดับความเสี่ยงของ BREAK HUNTER ยังไม่ได้ระบุ จึงเว้นข้อมูลเหล่านี้ไว้ใน eas.json
- ยังต้องใส่รูปของ 12 EA เดิมตาม IMAGE_FILES.txt เช่นเดียวกับแพ็กเดิม
