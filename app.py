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

# محاولة استيراد مكتبة OCR (تأكد من إضافتها لـ requirements.txt)
try:
    import easyocr
    import numpy as np
except ImportError:
    easyocr = None

# 1. إعدادات الصفحة
st.set_page_config(page_title="MedMate | رفيقك في الكلية", page_icon="🧬", layout="centered")

# --- CSS المظهر (RTL + Clean UI) ---
st.markdown("""
<style>
.stApp { direction: rtl; text-align: right; background-color: #f8f9fa; }
h1, h2, h3, p, div, .stMarkdown, .caption { text-align: right; font-family: 'Segoe UI', sans-serif; }
div.stButton > button { background-color: #2E86C1; color: white; width: 100%; font-weight: bold; border-radius: 8px; }
#MainMenu, footer, header {visibility: hidden;}
div[class^="viewerBadge"] {display: none !important;}
</style>
""", unsafe_allow_html=True)

# قائمة الأذكار
AZKAR_LIST = ["سبحان الله وبحمده 🌿", "اللهم صلِ على محمد ﷺ", "لا حول ولا قوة إلا بالله", "أستغفر الله وأتوب إليه"]

# إعدادات الأمان
try:
    GOOGLE_SHEET_URL = st.secrets["GOOGLE_SHEET_URL"]
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    GOOGLE_SHEET_URL = ""
    api_key = None

# --- دوال المعالجة (PDF و Word تظل كما هي في كودك السابق) ---
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

# (أضف دوال add_markdown_paragraph و create_styled_word_doc هنا كما في الكود السابق)

# --- دالة التحويل بنظام OCR التقليدي (بدون AI) ---
def process_with_standard_ocr(image_files):
    if easyocr is None:
        return "⚠️ مكتبة EasyOCR غير مثبتة. يرجى إضافتها لـ requirements.txt"
    
    reader = easyocr.Reader(['en', 'ar']) # دعم الإنجليزية والعربية
    full_text = ""
    for file in image_files:
        img = Image.open(file)
        img_np = np.array(img)
        results = reader.readtext(img_np, detail=0)
        full_text += f"\n\n--- نتائج OCR لملف: {file.name} ---\n" + " ".join(results)
    return full_text

# ---------------------------------------------------------
# الواجهة الرئيسية (UI)
# ---------------------------------------------------------
st.title("MedMate | رفيقك الذكي 🧬") 

# صندوق الملاحظات
st.markdown("""<div style="background-color: #e8f4fd; padding: 15px; border-radius: 10px; border: 1px solid #2E86C1;">
💌 <b>صدقة جارية</b> لدفعة طب بني سويف.</div>""", unsafe_allow_html=True)

st.divider()

# 1. منطقة الرفع
uploaded_files = st.file_uploader("📂 ارفع الصور أو ملفات PDF", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

st.divider()

# 2. الاختيار الجديد (AI vs OCR) 🆕
st.subheader("🛠️ اختر طريقة المعالجة")
conversion_method = st.radio(
    "كيف تريد معالجة الملفات؟",
    options=["الذكاء الاصطناعي (أفضل تنسيق + ذكاء طبي) ✨", "نظام OCR العادي (سريع + بلا حدود يومية) 📄"],
    help="الذكاء الاصطناعي يفهم الكلام الطبي وينسقه كملف ورد احترافي، أما الـ OCR فيقوم باستخراج النص فقط."
)

st.divider()

# إعدادات الملف
doc_type_selection = st.selectbox("نوع المحتوى:", options=["Lecture / Notes", "Exam / MCQ"], index=0)
col_opt1, col_opt2 = st.columns(2)
with col_opt1: is_handwritten = st.checkbox("✍️ خط يد؟")
with col_opt2: user_filename = st.text_input("اسم الملف:", value="MedMate Note")

# 3. زر التحويل والمنطق الذكي
if st.button("توكلنا على الله.. ابدأ التحويل 🚀"):
    if not uploaded_files:
        st.warning("⚠️ ارفع الملفات أولاً.")
    elif not api_key and "الذكاء الاصطناعي" in conversion_method:
        st.error("⚠️ مفتاح API مفقود.")
    else:
        status_text = st.empty()
        image_files = [f for f in uploaded_files if f.type in ['image/png', 'image/jpeg', 'image/jpg']]
        
        # --- الحالة الأولى: اختيار OCR العادي مباشرة ---
        if "OCR العادي" in conversion_method:
            status_text.markdown("**⚙️ جاري التحويل بنظام OCR التقليدي...**")
            with st.spinner("انتظر قليلاً..."):
                final_content = process_with_standard_ocr(image_files)
                st.session_state['converted_text'] = final_content
                status_text.success("✅ تم التحويل بنظام OCR!")

        # --- الحالة الثانية: اختيار الذكاء الاصطناعي مع معالجة أخطاء الرصيد ---
        else:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                status_text.markdown(f"**⏳ جاري التحليل بالذكاء الاصطناعي.. {random.choice(AZKAR_LIST)}** 📿")
                
                # دمج الصور لتقليل الـ RPD كما اتفقنا
                pdf_data = convert_images_to_pdf(image_files)
                temp_name = f"merged_{int(time.time())}.pdf"
                with open(temp_name, "wb") as f: f.write(pdf_data.read())
                
                google_file = genai.upload_file(temp_name)
                while google_file.state.name == "PROCESSING":
                    time.sleep(1)
                    google_file = genai.get_file(google_file.name)
                
                response = model.generate_content([get_medical_prompt(doc_type_selection, is_handwritten), google_file])
                st.session_state['converted_text'] = response.text
                os.remove(temp_name)
                status_text.success("✅ تم التحويل بنجاح!")
                st.balloons()

            except Exception as e:
                # التحقق لو الخطأ بسبب الرصيد (RPD Limit)
                if "429" in str(e) or "quota" in str(e).lower():
                    st.error("🛑 عذراً يا دكتور! تم الوصول للحد الأقصى المسموح به للذكاء الاصطناعي اليوم.")
                    st.info("💡 هل تود تحويل الملف الآن باستخدام نظام OCR العادي كحل مؤقت؟")
                    if st.button("نعم، حول باستخدام OCR 📄"):
                        # إعادة تنفيذ عملية الـ OCR
                        final_content = process_with_standard_ocr(image_files)
                        st.session_state['converted_text'] = final_content
                        st.rerun()
                else:
                    st.error(f"خطأ تقني: {e}")

# (عرض النتائج في الأسفل)
