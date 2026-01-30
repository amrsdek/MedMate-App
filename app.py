import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from prompts import get_medical_prompt
import io
import os
import requests
import random
import time
import threading

# 1. إعدادات الصفحة
st.set_page_config(page_title="MedMate | رفيقك في الكلية", page_icon="🧬", layout="centered")

# ---------------------------------------------------------
# CSS للمظهر (RTL + إخفاء كامل لعلامات Streamlit - Clean UI)
# ---------------------------------------------------------
st.markdown("""
<style>
/* 1. إعدادات RTL واتجاه الصفحة */
.stApp {
    direction: rtl;
    text-align: right;
    background-color: #f8f9fa;
}

/* 2. تنسيق النصوص والعناوين */
h1, h2, h3, p, div, .stMarkdown, .caption {
    text-align: right; 
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

/* 3. تنسيق القوائم الجانبية */
section[data-testid="stSidebar"] {
    direction: rtl;
    text-align: right;
}

/* 4. تنسيق المدخلات */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
    direction: rtl;
    text-align: right;
}
.stCheckbox { direction: rtl; text-align: right; }

/* 5. تنسيق الأزرار */
div.stButton > button {
    background-color: #2E86C1;
    color: white;
    font-size: 18px;
    padding: 10px 20px;
    border-radius: 8px;
    border: none;
    width: 100%;
    margin-top: 20px;
    font-weight: bold;
}

/* 6. تنسيق التنبيهات */
.stAlert { direction: rtl; text-align: right; font-weight: bold; }

/* ----------------------------------------------------------- */
/* 🚫 منطقة الإخفاء القسري (إخفاء الهوية والفوتر) */
/* ----------------------------------------------------------- */
#MainMenu {visibility: hidden;}
footer {visibility: hidden !important; height: 0px !important;}
header {visibility: hidden !important;}
div[class^="viewerBadge"] {display: none !important;}
div[class*="viewerBadge"] {display: none !important;}
.stDeployButton {display:none !important;}
[data-testid="stToolbar"] {visibility: hidden !important;}

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# قائمة الأذكار (تظهر أثناء التحميل)
# ---------------------------------------------------------
AZKAR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم 🌿",
    "اللهم صل وسلم وبارك على نبينا محمد ﷺ",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم إنك عفو كريم تحب العفو فاعف عنا",
    "يا حي يا قيوم برحمتك أستغيث",
    "ربّ اشرح لي صدري ويسّر لي أمري"
]

# ---------------------------------------------------------
# 🔐 إعدادات الأمان (Secrets)
# ---------------------------------------------------------
try:
    GOOGLE_SHEET_URL = st.secrets["GOOGLE_SHEET_URL"]
except:
    GOOGLE_SHEET_URL = ""

try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    api_key = None

# ---------------------------------------------------------
# دوال التنسيق (Word Functions)
# ---------------------------------------------------------
def add_markdown_paragraph(parent, text, style='Normal', align=None):
    if hasattr(parent, 'add_paragraph'): p = parent.add_paragraph(style=style)
    else: p = parent 
    if align: p.alignment = align
    else: p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in text) else WD_ALIGN_PARAGRAPH.LEFT
    
    parts = text.split('**')
    for i, part in enumerate(parts):
        if not part: continue
        run = p.add_run(part)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        if i % 2 == 1: run.font.bold = True
        else: run.font.bold = False
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
    main_heading = doc.add_heading(user_title, 0)
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
        
        # تنظيف العناوين من #
        if line.startswith('#'):
            clean_text = line.lstrip('#').strip().replace('**', '')
            h = doc.add_heading(clean_text, level=1)
            h.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in line) else WD_ALIGN_PARAGRAPH.LEFT
            for run in h.runs:
                run.font.name = 'Times New Roman'; run.font.size = Pt(14); run.font.bold = True; run.font.color.rgb = RGBColor(0, 0, 0)
        elif line.startswith('* ') or line.startswith('- '):
            clean_text = line.replace('* ', '', 1).replace('- ', '', 1)
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

st.markdown("""
<div style="text-align: right; direction: rtl;">
<h3>حوّل صور المحاضرات لملفات Word في ثوانٍ! ⚡</h3>
من أخ لأخيه.. طورنا <b>MedMate</b> عشان يكون رفيقك في المشوار.
<br>
صور المحاضرة، ارفعها هنا، واستلمها ملف Word منسق وجاهز للمذاكرة فوراً.
<br>
<small style="color: #666;">* متاح مجاناً لدفعة طب بني سويف.</small>
</div>
""", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------
# 1. صندوق الملاحظات (تم نقله هنا: في المقدمة) 🆕
# ---------------------------------------------------------
st.markdown("""
<div style="text-align: right; direction: rtl; background-color: #e8f4fd; padding: 15px; border-radius: 10px; border: 1px solid #2E86C1;">
    <h4 style="margin:0;">💌 رسالة ودعوة</h4>
    <p style="font-size: 14px; color: #555; margin-top: 5px;">
    العمل ده <b>صدقة جارية</b> لدفعة طب بني سويف. لو الأداة فادتك، ادعِ للقائمين عليها بظهر الغيب. ❤️<br>
    ولو واجهتك مشكلة، ابعتها هنا وهنحلها فوراً بإذن الله.
    </p>
</div>
""", unsafe_allow_html=True)

with st.form(key='feedback_form'):
    feedback_text = st.text_area("رسالتك:", placeholder="اكتب دعوتك أو اقتراحك هنا...")
    submit_feedback = st.form_submit_button(label='إرسال (Send) 📨')
    
    if submit_feedback:
        if feedback_text:
            if not GOOGLE_SHEET_URL:
                st.warning("⚠️ خدمة الرسائل غير مفعلة.")
            else:
                try:
                    response = requests.post(GOOGLE_SHEET_URL, json={"feedback": feedback_text})
                    if response.status_code == 200:
                        st.success("جزاك الله خيراً! رسالتك وصلت ❤️")
                    else:
                        st.error("حدث خطأ في الاتصال.")
                except Exception as e:
                    st.error(f"خطأ: {e}")
        else:
            st.warning("الرجاء كتابة رسالة أولاً.")

st.divider()

if 'converted_text' not in st.session_state:
    st.session_state['converted_text'] = ""

# 2. منطقة الرفع
uploaded_files = st.file_uploader(
    "📂 ارفع صور المحاضرات (سبورة/ورق) أو ملفات PDF",
    type=['png', 'jpg', 'jpeg', 'pdf'], 
    accept_multiple_files=True
)
st.caption("💡 نصيحة أخوية: عشان الموقع يشتغل بسرعة، يفضل ترفع **10-15 صورة** أو **ملف PDF واحد (لا يزيد عن 50 صفحة)** في المرة الواحدة.")

st.divider()
st.subheader("⚙️ إعدادات الملف (Preferences)")

# 3. الإعدادات
doc_type_selection = st.selectbox(
    "نوع المحتوى (Output Format):",
    options=["Lecture / Notes", "Exam / MCQ"],
    index=None,
    placeholder="اختار نوع الملف يا دكتور.."
)

if doc_type_selection == "Lecture / Notes":
    st.info("ℹ️ للمحاضرات والمذكرات: هيتم التنسيق كفقرات وعناوين وشرح متصل.")
elif doc_type_selection == "Exam / MCQ":
    st.info("ℹ️ للامتحانات: هيتم التنسيق كأسئلة منفصلة واختيارات دقيقة.")

col_opt1, col_opt2 = st.columns(2)
with col_opt1: is_handwritten = st.checkbox("✍️ هل الملف بخط اليد؟")
with col_opt2: user_filename = st.text_input("اسم الملف الناتج:", value="MedMate Note")

# 4. زر التحويل
if st.button("توكلنا على الله.. ابدأ التحويل 🚀"):
    if not uploaded_files: st.warning("⚠️ الرجاء رفع الملفات أولاً.")
    elif not api_key: st.error("⚠️ لم يتم العثور على مفتاح API في الإعدادات! يرجى التواصل مع المطور.")
    elif doc_type_selection is None: st.error("🛑 يجب اختيار نوع المحتوى لضمان جودة الملف.")
    else:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-flash-latest')
        full_combined_text = ""
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            for i, uploaded_file in enumerate(uploaded_files):
                prompt_type = "Exam / MCQ" if doc_type_selection == "Exam / MCQ" else "Lecture / Notes"
                prompt = get_medical_prompt(prompt_type, is_handwritten)
                
                # قراءة الملفات في الخيط الرئيسي لمنع التجمد
                file_bytes = uploaded_file.getvalue()
                file_type = uploaded_file.type
                file_name = uploaded_file.name
                
                # حاوية للنتيجة
                thread_result = {"text": None, "error": None}

                # دالة المعالجة الخلفية
                def process_file_in_background():
                    try:
                        if file_type in ['image/png', 'image/jpeg', 'image/jpg']:
                            response = model.generate_content([prompt, {"mime_type": file_type, "data": file_bytes}])
                            thread_result["text"] = f"\n\nSource: {file_name}\n" + response.text
                        
                        elif file_type == 'application/pdf':
                            temp_filename = f"temp_{int(time.time())}_{random.randint(1000,9999)}.pdf"
                            with open(temp_filename, "wb") as f: f.write(file_bytes)
                            
                            uploaded_pdf = genai.upload_file(temp_filename)
                            while uploaded_pdf.state.name == "PROCESSING":
                                time.sleep(1)
                                uploaded_pdf = genai.get_file(uploaded_pdf.name)

                            response = model.generate_content([prompt, uploaded_pdf])
                            thread_result["text"] = f"\n\nSource: {file_name}\n" + response.text
                            try: os.remove(temp_filename)
                            except: pass
                    except Exception as e:
                        thread_result["error"] = e

                # بدء المعالجة في خيط منفصل
                t = threading.Thread(target=process_file_in_background)
                t.start()

                # حلقة الأذكار أثناء الانتظار
                while t.is_alive():
                    current_zikr = random.choice(AZKAR_LIST)
                    status_text.markdown(f"**جاري تحليل الملف ({i+1}/{len(uploaded_files)}).. {current_zikr}** 📿")
                    time.sleep(2.5) 

                t.join()

                if thread_result["error"]:
                    raise thread_result["error"]
                
                if thread_result["text"]:
                    full_combined_text += thread_result["text"]
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.session_state['converted_text'] = full_combined_text
            status_text.success("✅ Done! الملف جاهز للتحميل بالأسفل.")
            st.balloons()
            
        except Exception as e:
            st.error(f"خطأ تقني: {e}")

# ---------------------------------------------------------
# 5. عرض النتائج
# ---------------------------------------------------------
if st.session_state['converted_text']:
    st.divider()
    docx_file = create_styled_word_doc(st.session_state['converted_text'], user_filename)
    col_download_area, col_info = st.columns([2, 1])
    with col_download_area:
        st.success("🎉 ملفك جاهز يا بطل! حمل من هنا:")
        st.download_button(
            label=f"💾 تحميل ملف الوورد ({user_filename}.docx)",
            data=docx_file.getvalue(),
            file_name=f"{user_filename}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )
    
    st.subheader("📝 مراجعة النص (Live Editor)")
    tab1, tab2 = st.tabs(["✍️ تعديل الكلام", "👁️ المعاينة"])
    with tab1:
        edited_text = st.text_area("عدل براحتك هنا:", value=st.session_state['converted_text'], height=500, label_visibility="collapsed")
        if edited_text != st.session_state['converted_text']: st.session_state['converted_text'] = edited_text
    with tab2: st.markdown(st.session_state['converted_text'])
