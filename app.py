import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from prompts import get_medical_prompt
from PIL import Image
import io
import os
import requests
import random
import time
import threading

# 1. إعدادات الصفحة
st.set_page_config(page_title="MedMate | رفيقك في الكلية", page_icon="🧬", layout="centered")

# ---------------------------------------------------------
# CSS للمظهر (RTL + إخفاء كامل لعلامات Streamlit)
# ---------------------------------------------------------
st.markdown("""
<style>
.stApp { direction: rtl; text-align: right; background-color: #f8f9fa; }
h1, h2, h3, p, div, .stMarkdown, .caption { text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, sans-serif; }
section[data-testid="stSidebar"] { direction: rtl; text-align: right; }
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] { direction: rtl; text-align: right; }
.stCheckbox { direction: rtl; text-align: right; }
div.stButton > button {
    background-color: #2E86C1; color: white; font-size: 18px; padding: 10px 20px;
    border-radius: 8px; border: none; width: 100%; margin-top: 20px; font-weight: bold;
}
.stAlert { direction: rtl; text-align: right; font-weight: bold; }
/* 🚫 منطقة الإخفاء القسري (Clean UI) */
#MainMenu {visibility: hidden;}
footer {visibility: hidden !important; height: 0px !important;}
header {visibility: hidden !important;}
div[class^="viewerBadge"] {display: none !important;}
div[class*="viewerBadge"] {display: none !important;}
.stDeployButton {display:none !important;}
[data-testid="stToolbar"] {visibility: hidden !important;}
</style>
""", unsafe_allow_html=True)

# قائمة الأذكار
AZKAR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم 🌿", "اللهم صل وسلم وبارك على نبينا محمد ﷺ",
    "لا حول ولا قوة إلا بالله العلي العظيم", "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر", "اللهم إنك عفو كريم تحب العفو فاعف عنا",
    "يا حي يا قيوم برحمتك أستغيث", "ربّ اشرح لي صدري ويسّر لي أمري"
]

# إعدادات الأمان
try:
    GOOGLE_SHEET_URL = st.secrets["GOOGLE_SHEET_URL"]
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    GOOGLE_SHEET_URL = ""
    api_key = None

# --- وظيفة تحويل الصور لـ PDF لتوفير الرصيد (RPD Saver) ---
def convert_images_to_pdf(image_files):
    images = []
    for file in image_files:
        img = Image.open(file)
        if img.mode != 'RGB': img = img.convert('RGB')
        images.append(img)
    if not images: return None
    pdf_io = io.BytesIO()
    images[0].save(pdf_io, format='PDF', save_all=True, append_images=images[1:])
    pdf_io.seek(0)
    return pdf_io

# --- دوال التنسيق (Word Functions) مع تنظيف علامات * ---
def add_markdown_paragraph(parent, text, style='Normal', align=None):
    if hasattr(parent, 'add_paragraph'): p = parent.add_paragraph(style=style)
    else: p = parent 
    # مسح النجوم المفردة والإبقاء على دبل ستار للبولد فقط
    text = text.replace('***', '**').replace('*', '') 
    if align: p.alignment = align
    else: p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in text) else WD_ALIGN_PARAGRAPH.LEFT
    parts = text.split('**')
    for i, part in enumerate(parts):
        if not part: continue
        run = p.add_run(part)
        run.font.name = 'Times New Roman'; run.font.size = Pt(12)
        run.font.bold = True if i % 2 == 1 else False
    return p

def add_page_border(doc):
    sec_pr = doc.sections[0]._sectPr
    pg_borders = OxmlElement('w:pgBorders')
    pg_borders.set(qn('w:offsetFrom'), 'page')
    for border_name in ('top', 'left', 'bottom', 'right'):
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single'); border.set(qn('w:sz'), '12'); border.set(qn('w:space'), '24'); border.set(qn('w:color'), 'auto')
        pg_borders.append(border)
    sec_pr.append(pg_borders)

def create_word_table(doc, table_lines):
    if not table_lines: return
    cleaned_rows = []
    for line in table_lines:
        if '---' in line: continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        cleaned_rows.append(cells)
    if not cleaned_rows: return
    table = doc.add_table(rows=len(cleaned_rows), cols=len(cleaned_rows[0]))
    table.style = 'Table Grid'
    for r_idx, row_data in enumerate(cleaned_rows):
        row = table.rows[r_idx]
        for c_idx, cell_text in enumerate(row_data):
            if c_idx < len(row.cells):
                cell = row.cells[c_idx]; cell.text = "" 
                p = cell.paragraphs[0]
                add_markdown_paragraph(p, cell_text, align=WD_ALIGN_PARAGRAPH.CENTER if r_idx==0 else None)
                if r_idx == 0: 
                    for run in p.runs: run.font.bold = True
    doc.add_paragraph("")

def create_styled_word_doc(text_content, user_title):
    doc = Document()
    add_page_border(doc)
    style = doc.styles['Normal']; font = style.font; font.name = 'Times New Roman'; font.size = Pt(12)
    # تنظيف العنوان
    clean_title = user_title.replace('*', '').replace('#', '').strip()
    main_heading = doc.add_heading(clean_title, 0)
    main_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in main_heading.runs:
        run.font.name = 'Times New Roman'; run.font.size = Pt(16); run.font.bold = True; run.font.color.rgb = RGBColor(0, 0, 0)
    lines = text_content.split('\n')
    table_buffer = []
    for line in lines:
        line = line.strip()
        if line.startswith('|') and line.endswith('|'):
            table_buffer.append(line); continue
        else:
            if table_buffer: create_word_table(doc, table_buffer); table_buffer = []
        if not line: continue
        if line.startswith('#'):
            clean_text = line.lstrip('#').replace('*', '').strip()
            h = doc.add_heading(clean_text, level=1)
            h.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in line) else WD_ALIGN_PARAGRAPH.LEFT
            for run in h.runs:
                run.font.name = 'Times New Roman'; run.font.size = Pt(14); run.font.bold = True; run.font.color.rgb = RGBColor(0, 0, 0)
        elif line.startswith('* ') or line.startswith('- '):
            clean_text = line.lstrip('* ').lstrip('- ').replace('*', '').strip()
            add_markdown_paragraph(doc, clean_text, style='List Bullet')
        else:
            add_markdown_paragraph(doc, line)
    if table_buffer: create_word_table(doc, table_buffer)
    bio = io.BytesIO(); doc.save(bio)
    return bio

# ---------------------------------------------------------
# الواجهة الرئيسية (UI)
# ---------------------------------------------------------
st.title("MedMate | رفيقك الذكي في الكلية 🧬") 
st.markdown("""<div style="text-align: right; direction: rtl;"><h3>حوّل صور المحاضرات لملفات Word في ثوانٍ! ⚡</h3>
<small style="color: #666;">* متاح مجاناً لدفعة طب بني سويف.</small></div>""", unsafe_allow_html=True)

st.divider()

# 1. صندوق الملاحظات (متاح دائماً)
st.markdown("""<div style="background-color: #e8f4fd; padding: 15px; border-radius: 10px; border: 1px solid #2E86C1;">
<h4 style="margin:0;">💌 رسالة ودعوة</h4>
<p style="font-size: 14px; color: #555; margin-top: 5px;">العمل ده <b>صدقة جارية</b> لدفعة طب بني سويف. ادعِ للقائمين عليه بظهر الغيب. ❤️</p>
</div>""", unsafe_allow_html=True)
with st.form(key='feedback_form'):
    feedback_text = st.text_area("رسالتك:", placeholder="اكتب دعوتك أو اقتراحك هنا...")
    submit_feedback = st.form_submit_button(label='إرسال الرسالة 📨')
    if submit_feedback and feedback_text and GOOGLE_SHEET_URL:
        try: requests.post(GOOGLE_SHEET_URL, json={"feedback": feedback_text}); st.success("وصلت ❤️")
        except: st.error("عذراً، حدث خطأ.")

st.divider()
if 'converted_text' not in st.session_state: st.session_state['converted_text'] = ""

# 2. منطقة الرفع والخيارات
uploaded_files = st.file_uploader("📂 ارفع الصور أو ملفات PDF", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)
doc_type_selection = st.selectbox("نوع المحتوى:", options=["Lecture / Notes", "Exam / MCQ"], index=None, placeholder="اختار النوع..")
col_opt1, col_opt2 = st.columns(2)
with col_opt1: is_handwritten = st.checkbox("✍️ خط يد؟")
with col_opt2: user_filename = st.text_input("اسم الملف:", value="MedMate Note")

# 3. زر التحويل (المنطق الموفر للرصيد + الأذكار)
if st.button("توكلنا على الله.. ابدأ التحويل 🚀"):
    if not uploaded_files: st.warning("⚠️ ارفع الملفات أولاً.")
    elif not api_key: st.error("⚠️ مفتاح API مفقود.")
    elif doc_type_selection is None: st.error("🛑 اختر نوع المحتوى.")
    else:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-flash-latest')
        status_text = st.empty(); progress_bar = st.progress(0)
        try:
            image_files = [f for f in uploaded_files if f.type in ['image/png', 'image/jpeg', 'image/jpg']]
            pdf_files = [f for f in uploaded_files if f.type == 'application/pdf']
            final_content = ""
            
            # أ- معالجة الصور ككتلة واحدة (PDF واحد = طلب واحد)
            if image_files:
                status_text.markdown(f"**📦 جاري دمج {len(image_files)} صور لتوفير الرصيد...**")
                pdf_data = convert_images_to_pdf(image_files)
                temp_name = f"merged_{int(time.time())}.pdf"
                with open(temp_name, "wb") as f: f.write(pdf_data.read())
                
                thread_result = {"text": None, "error": None}
                def process():
                    try:
                        g_file = genai.upload_file(temp_name)
                        while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)
                        response = model.generate_content([get_medical_prompt(doc_type_selection, is_handwritten), g_file])
                        thread_result["text"] = response.text
                    except Exception as e: thread_result["error"] = e
                
                t = threading.Thread(target=process); t.start()
                while t.is_alive():
                    status_text.markdown(f"**⏳ جاري التحليل.. {random.choice(AZKAR_LIST)}** 📿")
                    time.sleep(2.5)
                t.join()
                if thread_result["error"]: raise thread_result["error"]
                final_content += thread_result["text"]; os.remove(temp_name)
                progress_bar.progress(0.5 if pdf_files else 1.0)

            # ب- معالجة ملفات PDF المرفوعة
            for i, pdf in enumerate(pdf_files):
                status_text.markdown(f"**📑 جاري تحليل {pdf.name}... {random.choice(AZKAR_LIST)}**")
                temp_pdf = f"temp_{pdf.name}"
                with open(temp_pdf, "wb") as f: f.write(pdf.getvalue())
                g_pdf = genai.upload_file(temp_pdf)
                while g_pdf.state.name == "PROCESSING": time.sleep(1); g_pdf = genai.get_file(g_pdf.name)
                response = model.generate_content([get_medical_prompt(doc_type_selection, is_handwritten), g_pdf])
                final_content += f"\n\nSource: {pdf.name}\n" + response.text
                os.remove(temp_pdf)
                progress_bar.progress((i + 1) / len(pdf_files))

            st.session_state['converted_text'] = final_content
            status_text.success("✅ تم التحويل بنجاح يا بطل!"); st.balloons()
        except Exception as e: st.error(f"خطأ: {e}")

# 4. عرض النتائج
if st.session_state['converted_text']:
    st.divider()
    docx_file = create_styled_word_doc(st.session_state['converted_text'], user_filename)
    st.success("🎉 ملفك جاهز!")
    st.download_button(label=f"💾 تحميل ملف الوورد ({user_filename}.docx)", data=docx_file.getvalue(), file_name=f"{user_filename}.docx", use_container_width=True)
    st.subheader("📝 مراجعة النص")
    tab1, tab2 = st.tabs(["✍️ تعديل", "👁️ معاينة"])
    with tab1:
        edited = st.text_area("عدل هنا:", value=st.session_state['converted_text'], height=400, label_visibility="collapsed")
        st.session_state['converted_text'] = edited
    with tab2: st.markdown(st.session_state['converted_text'])
