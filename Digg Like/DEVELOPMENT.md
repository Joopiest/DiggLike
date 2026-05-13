# เอกสารรายละเอียดการพัฒนาแอปพลิเคชัน: My Local Digg Aggregator

เอกสารฉบับนี้จัดทำขึ้นเพื่ออธิบายรายละเอียดการพัฒนา โครงสร้างระบบ และคุณสมบัติต่างๆ ของแอปพลิเคชัน **My Local Digg Aggregator** ตามมาตรฐานการพัฒนาซอฟต์แวร์

---

## 1. ข้อมูลทั่วไปของโครงการ (Project Overview)

*   **ชื่อโครงการ:** My Local Digg Aggregator
*   **ภาษาที่ใช้:** Python 3.x, JavaScript (HTML5 Canvas)
*   **Framework หลัก:** Streamlit
*   **วัตถุประสงค์:** เป็นระบบรวบรวมข่าวสารและกระทู้ยอดนิยมจากแหล่งต่างๆ (News Aggregator) โดยได้รับแรงบันดาลใจจากเว็บ Digg ในอดีต มีระบบให้คะแนน (Digg/Bury) เพื่อดันข่าวที่น่าสนใจขึ้นด้านบน และมีหน้าจอแสดงผลแบบ Visualizer (Falling Blocks)

---

## 2. โครงสร้างระบบและสถาปัตยกรรม (System Architecture)

แอปพลิเคชันนี้ทำงานแบบ Single-file application เป็นหลัก โดยใช้ Streamlit เป็นทั้ง Frontend และ Backend ในตัว และมีการฝังโค้ด JavaScript เพื่อทำส่วน Visualizer

### 2.1 ส่วนประกอบของระบบ (Components)

1.  **Main Application (`Digg.py`):** ควบคุมการทำงานทั้งหมดของระบบ ตั้งแต่การดึงข้อมูล การประมวลผล การจัดการ State และการแสดงผล UI
2.  **Background Fetcher:** Thread แยกทำงานในพื้นหลังเพื่อดึงข้อมูลใหม่โดยอัตโนมัติตามเวลาที่กำหนด
3.  **Visualizer (HTML5 Canvas):** ใช้ JavaScript ในการวาดกราฟิกกล่องข่าวร่วงหล่น (Falling Blocks) เพื่อแสดงความหนาแน่นและปริมาณของข่าวในแต่ละหมวดหมู่

### 2.2 โครงสร้างไฟล์ (File Structure)

```text
d:/JoopFirebase/Digg Like/
├── Digg.py                 # ไฟล์โค้ดหลักของแอปพลิเคชัน
├── requirements.txt        # ไฟล์ระบุ Dependencies ที่ต้องใช้
├── current_feed.json       # [Runtime] เก็บข้อมูล Feed ล่าสุดที่ผ่านการฟิลเตอร์แล้ว
├── last_fetch.txt         # [Runtime] เก็บ Timestamp ของการดึงข้อมูลล่าสุด
├── running_state.txt      # [Runtime] เก็บสถานะการทำงาน (START/STOP)
└── .gitignore             # ไฟล์ยกเว้นการติดตามของ Git (ไม่รวมไฟล์ Runtime)
```

---

## 3. คุณสมบัติหลัก (Key Features)

### 3.1 การดึงข้อมูลและจัดหมวดหมู่ (Data Fetching & Categorization)
*   **แหล่งข้อมูล:** รองรับการดึงข้อมูลจากหลายแหล่ง เช่น Reddit, Pantip, Google News, BBC, CNN, Al Jazeera, Blognone และอื่นๆ
*   **ระบบ Categorization อัตโนมัติ:** ใช้ระบบ Keyword Matching ในการวิเคราะห์หัวข้อข่าวและจัดเข้าหมวดหมู่โดยอัตโนมัติ เช่น ข่าวด่วน, เทคโนโลยี, การเงิน, บันเทิง ฯลฯ

### 3.2 ระบบการให้คะแนน (Scoring & Voting System)
*   **Base Score:** กำหนดคะแนนเริ่มต้นให้แต่ละแหล่งข่าวไม่เท่ากัน (เช่น Pantip และ Reddit จะมีคะแนนดิบมาจากต้นทาง)
*   **User Vote:** ผู้ใช้สามารถกด **Digg (▲)** หรือ **Bury (▼)** ได้
    *   การกด Digg จะเพิ่มคะแนนอย่างมาก (เพื่อการจัดเรียงที่เห็นผลทันที)
    *   ระบบคำนวณคะแนนรวม: `Total Score = Base Score + (User Vote * 5000)`

### 3.3 การแสดงผลแบบ Visualizer (Digg Stack)
*   แสดงผลในแท็บ "📊 Digg Stack"
*   ข่าวแต่ละเรื่องจะตกลงมาเป็นกล่องตามหมวดหมู่
*   **ความสูงของกล่อง:** แปรผันตามคะแนนของข่าวนั้นๆ
*   **สีของกล่อง:** แยกตามแหล่งที่มาของข่าว
*   **Interactivity:**
    *   สามารถเลื่อน Scroll ดูในแต่ละคอลัมน์ได้อิสระ
    *   เมื่อนำเมาส์ไปชี้ (Hover) จะแสดงกล่อง Tooltip บอกชื่อแหล่งข่าว, เวลาที่ Fetch และพาดหัวข่าวแบบเต็ม
    *   คลิกที่กล่องเพื่อเปิดลิงก์ข่าวไปยังแท็บใหม่

### 3.4 ระบบ Auto Refresh & Timezone
*   สามารถตั้งเวลาให้ดึงข้อมูลอัตโนมัติได้ (Background Fetching)
*   มีระบบ Countdown แสดงเวลาที่จะดึงข้อมูลครั้งถัดไป
*   มี **Timezone Selector** ให้ผู้ใช้เลือก Timezone ของตัวเอง เพื่อให้การแสดงเวลาในระบบตรงกับเวลาจริงของผู้ใช้

---

## 4. รายละเอียดทางเทคนิค (Technical Details)

### 4.1 เทคโนโลยีที่ใช้ (Tech Stack)
*   **UI Framework:** Streamlit
*   **Data Parsing:** `feedparser` (สำหรับ RSS), `BeautifulSoup` (สำหรับ Web Scraping)
*   **Threading:** Python `threading` สำหรับทำ Background Task
*   **Frontend Canvas:** HTML5 Canvas API + Vanilla JavaScript

### 4.2 การจัดการ State
*   ใช้ `st.session_state` ในการเก็บ:
    *   `fetched_items`: รายการข่าวทั้งหมดที่ดึงมา
    *   `user_votes`: สถานะการโหวตของผู้ใช้ (โหวตบวก/ลบ)
    *   `running_state`: สถานะการทำงานของแอป

---

## 5. การติดตั้งและการใช้งาน (Installation & Usage)

### 5.1 การติดตั้ง
1.  ติดตั้ง Dependencies ที่จำเป็น:
    ```bash
    pip install -r requirements.txt
    ```

### 5.2 การรันแอปพลิเคชัน
1.  รันคำสั่ง Streamlit:
    ```bash
    streamlit run Digg.py
    ```
2.  เปิด Browser ไปที่ `http://localhost:8501`

---

## 6. บันทึกการปรับปรุงล่าสุด (Recent Updates)
*   **Timezone Support:** เพิ่มระบบเลือก Timezone และปรับปรุงการแสดงผลเวลาให้ตรงตามที่ผู้ใช้เลือก
*   **STOP Button Fix:** แก้ไขปุ่ม STOP ให้สามารถหยุดการทำงานของ Background Thread ได้จริงและเคลียร์ข้อมูลเก่าออก
*   **Tooltip Enhancement:** ปรับปรุง Tooltip ในหน้า Stack ให้แสดงข้อมูลครบถ้วน (แหล่งข่าว, เวลา, พาดหัวเต็ม)
