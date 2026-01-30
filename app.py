# ---------------------------------------------------------
# CSS للمظهر (RTL + إخفاء شعار Streamlit والمطور)
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

/* 7. 🚫 إخفاء جميع عناصر Streamlit الافتراضية (الهامبرغر والفوتر والشريط السفلي) */
#MainMenu {visibility: hidden;} /* يخفي الثلاث شرط اللي فوق */
footer {visibility: hidden;}    /* يخفي كلمة Made with Streamlit */
header {visibility: hidden;}    /* يخفي الشريط العلوي الملون */
.stDeployButton {display:none;} /* يخفي زر النشر */
[data-testid="stToolbar"] {visibility: hidden !important;} /* يخفي شريط الأدوات للمطور */
.viewerBadge_container__1QSob {display: none !important;} /* محاولة لإخفاء شريط العرض السفلي */

</style>
""", unsafe_allow_html=True)
