import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# ================================================================================
# [1] 유틸리티 함수
# ================================================================================
def normalize_date(date_str):
    """문자열에서 시간 등을 무시하고 YYYY.MM.DD 형식만 정확히 뽑아냅니다."""
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except:
        return date_str

# ================================================================================
# [2] GLC 리스트 페이지 크롤링 엔진 (새로 추가됨)
# ================================================================================
def get_glc_links(url):
    """GLC 공지사항 목록에서 '공지'를 제외하고 숫자 번호를 가진 일반 글 링크만 추출합니다."""
    links = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # KBoard 게시판의 목록 행(tr) 탐색
        rows = soup.find_all('tr')
        
        for row in rows:
            # 1. 번호 칼럼 추출
            uid_td = row.find('td', class_='kboard-list-uid')
            if not uid_td:
                continue
                
            uid_text = uid_td.get_text(strip=True)
            
            # ★ 필터링: 번호가 숫자가 아니면(예: '공지') 패스
            if not uid_text.isdigit():
                continue

            # 2. 제목 및 링크 추출
            title_td = row.find('td', class_='kboard-list-title')
            if title_td:
                a_tag = title_td.find('a')
                if a_tag:
                    href = a_tag.get('href')
                    full_url = urljoin(url, href)
                    
                    # 제목 텍스트 (kboard-default-cut-strings <div> 안의 텍스트 추출)
                    title_div = a_tag.find('div', class_='kboard-default-cut-strings')
                    title = title_div.get_text(strip=True) if title_div else a_tag.get_text(strip=True)

                    links.append({
                        "no": uid_text,
                        "title": title,
                        "url": full_url
                    })
        return links
    except Exception as e:
        print(f"목록 수집 에러: {e}")
        return []

# ================================================================================
# [3] GLC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_glc_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 추출
        title = "제목 없음"
        title_div = soup.find('div', class_='kboard-title')
        if title_div:
            h1_tag = title_div.find('h1')
            if h1_tag: title = h1_tag.get_text(strip=True)

        # 2. 작성일 추출
        date = "날짜 없음"
        date_div = soup.find('div', class_='detail-date')
        if date_div:
            val_div = date_div.find('div', class_='detail-value')
            if val_div: date = normalize_date(val_div.get_text(strip=True))

        # 3. 본문 및 4. 이미지 추출
        content_html = ""
        images = []
        
        content_div = soup.find('div', class_='content-view')
        
        if content_div:
            for idx, img in enumerate(content_div.find_all('img')):
                src = img.get('data-orig-src') or img.get('src', '')
                if src and not any(x in src for x in ['icon', 'btn', 'blank']):
                    if src.startswith('data:image'):
                        try:
                            header, encoded = src.split(',', 1)
                            data = base64.b64decode(encoded)
                            ext = "png"
                            if "jpeg" in header or "jpg" in header: ext = "jpg"
                            images.append({"type": "base64", "data": data, "name": f"image_{idx+1}.{ext}"})
                        except Exception: pass
                    else:
                        full_url = urljoin(url, src) 
                        parsed = urllib.parse.urlparse(full_url)
                        encoded_path = urllib.parse.quote(parsed.path)
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(parsed.path)
                        if not any(d.get('data') == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                
                img.decompose()
                
            for table in content_div.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출
        attachments = []
        buttons = soup.find_all('button', class_=lambda c: c and 'kboard-button-download' in c)
        for btn in buttons:
            fname = btn.get_text(strip=True)
            if fname and fname not in attachments:
                attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면 (공통 UI 포맷 적용)
# ================================================================================
st.set_page_config(page_title="GLC 공지 리스트 크롤러", layout="wide")
st.title("🌐 글로벌인재대학(GLC) 공지사항 리스트 추출기")
st.markdown("**목록 페이지**를 입력하면, 상단 고정 공지를 제외한 **최신 일반 게시물(번호 있는 것)**을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: center; }
th { background-color: #f8f9fa; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

list_url_input = st.text_input("🔗 GLC 공지사항 **목록(List)** URL", value="https://glc.yonsei.ac.kr/notice/?mod=list")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner('GLC 게시물 목록 스캔 중... (고정 공지는 제외합니다)'):
            post_links = get_glc_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 게시판 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 일반 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행 (Progress bar 적용)
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"#{item['no']}번 게시물 크롤링 중...", expanded=True):
                    # GLC 전용 상세 크롤링 함수 호출
                    title, date, content, images, attachments = scrape_glc_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### [{item['no']}] {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        # 본문
                        st.markdown(content, unsafe_allow_html=True)
                        
                        # 이미지
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3) if len(images) > 0 else 1)
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    st.image(img_item['data'], caption=img_item['name'], use_container_width=True)
                        
                        # 첨부파일 (줄바꿈 나열)
                        if attachments:
                            st.markdown("**📎 첨부파일:**\n" + "\n".join([f"- {att}" for att in attachments]))
                    else:
                        st.error("내용 추출 실패")
                
                # 진행률 업데이트
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")