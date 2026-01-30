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

# 1. إعدادات الصفحة
st.set_page_config(page_title="MedMate | رفيقك في الكلية", page_icon="🧬", layout="centered")

# ---------------------------------------------------------
# CSS للمظهر (RTL + تحسينات الواجهة العربية)
# ---------------------------------------------------------
st.markdown("""
<style>
/* 1. ضبط اتجاه الصفحة بالكامل لليمين */
.stApp {
    direction: rtl;
    text-align: right;
    background-color: #f8f9fa;
}

/* 2. ضبط العناوين والنصوص */
h1, h2, h3, p, div, .stMarkdown, .caption {
    text-align: right; 
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

/* 3. تعديل القوائم الجانبية (Sidebar) */
section[data-testid="stSidebar"] {
    direction: rtl;
    text-align: right;
}

/* 4. تعديل مدخلات النصوص والقوائم */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
    direction: rtl;
    text-align: right;
}

/* تعديل محاذاة الـ Checkbox */
.stCheckbox {
    direction: rtl;
    text-align: right;
}

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

/* 6. تحسين شكل التنبيهات */
.stAlert {
    direction: rtl;
    text-align: right;
    font-weight: bold;
}

/* 7. إخفاء القوائم الافتراضية */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# قائمة الأذكار (أثناء الانتظار)
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
# دوال التنسيق (Word Functions) - مع تنظيف الرموز
# ---------------------------------------------------------
def add_markdown_paragraph(parent, text, style='Normal', align=None):
    if hasattr(parent, 'add_paragraph'): p = parent.add_paragraph(style=style)
    else: p = parent 
    if align: p.alignment = align
    else: p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in text) else WD_ALIGN_PARAGRAPH.LEFT
    
    # تنظيف أي رموز ماركداون متبقية داخل الفقرات
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
        # معالجة الجداول
        if line.startswith('|') and line.endswith('|'):
            table_buffer.append(line); continue
        else:
            if table_buffer: create_word_table(doc, table_buffer); table_buffer = []
        
        if not line: continue
        
        # --- تنظيف العناوين (Headers) ---
        # استخدام lstrip لإزالة أي عدد من # سواء كانت # أو ## أو ###
        if line.startswith('#'):
            clean_text = line.lstrip('#').strip().replace('**', '')
            h = doc.add_heading(clean_text, level=1)
            # ضبط المحاذاة حسب اللغة
            h.alignment = WD_ALIGN_PARAGRAPH.RIGHT if any("\u0600" <= c <= "\u06FF" for c in line) else WD_ALIGN_PARAGRAPH.LEFT
            for run in h.runs:
                run.font.name = 'Times New Roman'; run.font.size = Pt(14); run.font.bold = True; run.font.color.rgb = RGBColor(0, 0, 0)
        
        # القوائم النقطية
        elif line.startswith('* ') or line.startswith('- '):
            clean_text = line.replace('* ', '', 1).replace('- ', '', 1)
            add_markdown_paragraph(doc, clean_text, style='List Bullet')
        # الفقرات العادية
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

if 'converted_text' not in st.session_state:
    st.session_state['converted_text'] = ""

# 1. منطقة الرفع
uploaded_files = st.file_uploader(
    "📂 ارفع صور المحاضرات (سبورة/ورق) أو ملفات PDF",
    type=['png', 'jpg', 'jpeg', 'pdf'], 
    accept_multiple_files=True
)
st.caption("💡 نصيحة أخوية: عشان الموقع يشتغل بسرعة، يفضل ترفع **10-15 صورة** أو **ملف PDF واحد (لا يزيد عن 50 صفحة)** في المرة الواحدة.")

st.divider()
st.subheader("⚙️ إعدادات الملف (Preferences)")

# 2. الإعدادات (Dropdown)
doc_type_selection = st.selectbox(
    "نوع المحتوى (Output Format):",
    options=["Lecture / Notes", "Exam / MCQ"],
    index=None,
    placeholder="اختار نوع الملف يا دكتور.."
)

# ظهور التوضيحات تلقائياً
if doc_type_selection == "Lecture / Notes":
    st.info("ℹ️ للمحاضرات والمذكرات: هيتم التنسيق كفقرات وعناوين وشرح متصل.")
elif doc_type_selection == "Exam / MCQ":
    st.info("ℹ️ للامتحانات: هيتم التنسيق كأسئلة منفصلة واختيارات دقيقة.")

col_opt1, col_opt2 = st.columns(2)
with col_opt1: is_handwritten = st.checkbox("✍️ هل الملف بخط اليد؟")
with col_opt2: user_filename = st.text_input("اسم الملف الناتج:", value="MedMate Note")

# 3. زر التحويل
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
                current_zikr = random.choice(AZKAR_LIST)
                status_text.markdown(f"**جاري تحليل الملف ({i+1}/{len(uploaded_files)}).. {current_zikr}** 📿")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
                prompt_type = "Exam / MCQ" if doc_type_selection == "Exam / MCQ" else "Lecture / Notes"
                prompt = get_medical_prompt(prompt_type, is_handwritten)
                
                if uploaded_file.type in ['image/png', 'image/jpeg', 'image/jpg']:
                    image_bytes = uploaded_file.getvalue()
                    response = model.generate_content([prompt, {"mime_type": uploaded_file.type, "data": image_bytes}])
                    # حذف علامة الشباك من المصدر
                    full_combined_text += f"\n\nSource: {uploaded_file.name}\n" + response.text
                elif uploaded_file.type == 'application/pdf':
                    temp_filename = f"temp_{uploaded_file.name}"
                    with open(temp_filename, "wb") as f: f.write(uploaded_file.getvalue())
                    uploaded_pdf = genai.upload_file(temp_filename)
                    response = model.generate_content([prompt, uploaded_pdf])
                    # حذف علامة الشباك من المصدر
                    full_combined_text += f"\n\nSource: {uploaded_file.name}\n" + response.text
                    try: os.remove(temp_filename)
                    except: pass
            
            st.session_state['converted_text'] = full_combined_text
            status_text.success("✅ Done! الملف جاهز للتحميل بالأسفل.")
            st.balloons()
        except Exception as e:
            st.error(f"خطأ تقني: {e}")

# 4. عرض النتائج (تعريب كامل)
if st.session_state['converted_text']:
    st.divider()
    docx_file = create_styled_word_doc(st.session_state['converted_text'], user_filename)
    col_download_area, col_info = st.columns([2, 1])
    with col_download_area:
        st.success("🎉 ملفك جاهز يا دكتور! حمل من هنا:")
        st.download_button(
            label=f"💾 تحميل ملف الوورد ({user_filename}.docx)",
            data=docx_file.getvalue(),
            file_name=f"{user_filename}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )
    st.divider()
    st.subheader("📝 مراجعة النص (Live Editor)")
    tab1, tab2 = st.tabs(["✍️ تعديل الكلام", "👁️ المعاينة"])
    with tab1:
        edited_text = st.text_area("عدل براحتك هنا:", value=st.session_state['converted_text'], height=500, label_visibility="collapsed")
        if edited_text != st.session_state['converted_text']: st.session_state['converted_text'] = edited_text
    with tab2: st.markdown(st.session_state['converted_text'])

# ---------------------------------------------------------
# صندوق الملاحظات (الصدقة الجارية)
# ---------------------------------------------------------
with st.sidebar:
    st.header("💌 رسالة ودعوة")
    st.markdown("""
    <div style="text-align: right; direction: rtl; font-size: 14px; color: #555;">
    العمل ده <b>صدقة جارية</b> لدفعة طب بني سويف.
    <br>
    لو الأداة فادتك، ادعِ للقائمين عليها بظهر الغيب دعوة حلوة. ❤️
    <br><br>
    ولو عندك اقتراح يطور <b>MedMate</b> أو واجهت مشكلة، ابعتها هنا.. إحنا هنا عشان نساعد بعض. 🚀
    </div>
    """, unsafe_allow_html=True)
    
    with st.form(key='feedback_form'):
        feedback_text = st.text_area("رسالتك:", placeholder="اكتب دعوتك أو اقتراحك هنا...")
        submit_feedback = st.form_submit_button(label='إرسال (Send) 📨')
        
        if submit_feedback:
            if feedback_text:
                if not GOOGLE_SHEET_URL:
                    st.warning("⚠️ خدمة الرسائل غير مفعلة (تأكد من الرابط السري).")
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

