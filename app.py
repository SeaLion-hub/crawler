import streamlit as st
import google.generativeai as genai
import os
import json
import datetime
from PIL import Image
from dotenv import load_dotenv

# 1. 환경변수 및 API 설정
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="DICE 공지 분석기", layout="wide")
st.title("🎲 DICE 공지사항 추출기 (Final)")

# 사이드바: 설정
st.sidebar.header("설정")
if not API_KEY:
    API_KEY = st.sidebar.text_input("Gemini API Key", type="password")

# 모델 목록 가져오기
available_models = []
if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
    except Exception as e:
        st.sidebar.error(f"API 키 오류: {e}")

# 모델 선택 (기본값: flash)
default_ix = 0
if "models/gemini-1.5-flash" in available_models:
    default_ix = available_models.index("models/gemini-1.5-flash")

selected_model_name = st.sidebar.selectbox(
    "사용할 모델 선택", 
    available_models, 
    index=default_ix if available_models else 0
)

# [중요] 모델 설정 시 temperature를 0으로 낮춰서 답변을 일관되게 만듦
if selected_model_name:
    generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}
    model = genai.GenerativeModel(selected_model_name, generation_config=generation_config)

# --- 핵심 로직 ---
def analyze_notice(title, body, image, post_date):
    
    # [강력해진 프롬프트] 예시를 JSON으로 직접 보여줘서 포맷을 강제함
    system_instruction = f"""
    너는 연세대학교 공지사항 데이터 추출 전문가야.
    
    [입력 정보]
    - 오늘 기준일(게시일): {post_date}
    
    [지시 사항]
    1. dates: 본문에 나온 모든 날짜와 시간을 리스트로 추출해.
    2. eligibility: 지원 자격을 **반드시 JSON 리스트(Array) 형태**로 쪼개서 추출해.
       - 만약 긴 문장이라면, 의미 단위로 쪼개서 리스트에 넣어.
    
    [출력 예시 - 반드시 이 JSON 포맷을 따를 것]
    {{
      "dates": [
        {{"type": "서류 마감", "date": "2026-01-21", "time": "17:00"}},
        {{"type": "면접", "date": "2026-01-30", "time": null}}
      ],
      "eligibility": [
        "3~4학년 재학생 (휴학생 불가)",
        "직전 학기 학점 80점 이상",
        "공과대학 소속 대학원생"
      ]
    }}
    """
    
    parts = [system_instruction]
    parts.append(f"공지 제목: {title}")
    if body:
        parts.append(f"공지 본문:\n{body}")
    if image:
        parts.append(image)
        parts.append("\n(이미지 내용을 분석해서 텍스트와 정보를 추출해)")
        
    try:
        response = model.generate_content(parts)
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

# --- UI 구성 ---
post_date = st.sidebar.date_input("공지 게시일", datetime.date.today())

with st.container():
    input_title = st.text_input("1️⃣ 공지 제목 (필수)", placeholder="공지 제목 입력")
    col1, col2 = st.columns(2)
    with col1:
        input_body = st.text_area("2️⃣ 공지 본문 (선택)", height=300)
    with col2:
        uploaded_file = st.file_uploader("3️⃣ 공지 이미지 (선택)", type=["jpg", "png", "jpeg", "webp"])
        input_image = None
        if uploaded_file is not None:
            input_image = Image.open(uploaded_file)
            st.image(input_image, caption="이미지 미리보기", use_column_width=True)

if st.button("🚀 정보 추출하기", type="primary", use_container_width=True):
    if not API_KEY or not model:
        st.error("⚠️ API 키 또는 모델 오류")
    elif not input_title.strip():
        st.error("⚠️ 제목을 입력해주세요.")
    else:
        with st.spinner("분석 중..."):
            result_text = analyze_notice(input_title, input_body, input_image, str(post_date))
            
            try:
                # JSON 파싱 로직 (마크다운 제거)
                json_str = result_text
                if "```json" in result_text:
                    json_str = result_text.split("```json")[1].split("```")[0]
                elif "```" in result_text:
                    json_str = result_text.split("```")[1].split("```")[0]
                
                data = json.loads(json_str)
                st.success("분석 완료!")
                
                res_col1, res_col2 = st.columns(2)
                
                # 1. 일정 (표)
                with res_col1:
                    st.subheader("📅 추출된 일정")
                    if "dates" in data and data["dates"]:
                        st.dataframe(data["dates"], hide_index=True, use_container_width=True)
                    else:
                        st.info("날짜 정보 없음")
                
                # 2. 자격 (리스트 변환 강제 로직)
                with res_col2:
                    st.subheader("✅ 지원 자격")
                    eli_data = data.get("eligibility", [])
                    
                    # Case A: 리스트로 잘 들어왔을 때 -> 하나씩 출력
                    if isinstance(eli_data, list) and len(eli_data) > 0:
                        for item in eli_data:
                            st.success(f"• {item}") 
                            
                    # Case B: 문자열로 뭉쳐서 들어왔을 때 -> 마침표(.)나 줄바꿈으로 억지로 쪼개서 출력
                    elif isinstance(eli_data, str) and eli_data.strip():
                        # 줄바꿈이나 마침표로 분리 시도
                        split_items = [x.strip() for x in eli_data.replace(".", "\n").split("\n") if x.strip()]
                        for item in split_items:
                            st.success(f"• {item}")
                            
                    # Case C: 진짜 없을 때
                    else:
                        st.warning("지원 자격 정보를 찾지 못했습니다. (원본 데이터를 확인하세요)")
                
                with st.expander("원본 JSON 데이터 확인 (디버깅용)"):
                    st.json(data)
                    
            except json.JSONDecodeError:
                st.error("결과 변환 실패. 아래 원본 텍스트를 확인하세요.")
                st.text(result_text)