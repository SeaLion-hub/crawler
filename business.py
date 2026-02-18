import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString, Comment, Tag
import base64
import re
import os
from urllib.parse import urljoin

# --- 페이지 설정 (경영대 전용) ---
st.set_page_config(page_title="연세 경영대학 공지 크롤러", layout="wide")
st.title("💼 연세 경영대학 공지사항 추출기 (독립형)")
st.markdown("목록(`td.Subject`) 필터링 + 본문(`BoardContent`) + 인코딩 자동 보정")

# --- [스타일] CSS ---
st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: center; }
th { background-color: #f8f9fa; font-weight: bold; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================

def normalize_date(date_str):
    """날짜 문자열을 YYYY.MM.DD로 표준화"""
    try:
        numbers = re.findall(r'\d+', date_str)
        if len(numbers) >= 3:
            y, m, d = numbers[:3]
            if len(y) == 2: y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except: return date_str

def clean_html_content(element):
    """HTML 본문 정제 (스크립트 제거, 표 보존, 하단 버튼 제거)"""
    import copy
    element = copy.copy(element)
    
    # 보안상 제거
    for tag in element.find_all(['script', 'style', 'noscript', 'iframe', 'img']):
        tag.decompose()

    # 하단 목록/수정 버튼 영역 제거
    for tag in element.find_all(id="boardicon"):
        tag.decompose()
        
    # 표 테두리 강제 적용
    for table in element.find_all('table'):
        if not table.get('border'): table['border'] = "1"
        
    return element.decode_contents().strip()

# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler)
# ==============================================================================

def get_business_notice_links(list_url):
    """
    경영대 게시판에서 <td class="Subject"> 내부의 링크만 수집
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(list_url, headers=headers)
        
        # ★ 경영대 인코딩 보정 (CP949/EUC-KR)
        response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = []
        
        # 1. <td class="Subject"> 찾기
        subjects = soup.find_all('td', class_='Subject')
        
        if not subjects:
            # 대소문자 문제일 수 있으므로 소문자로도 시도
            subjects = soup.find_all('td', class_='subject')

        for td in subjects:
            # 2. 링크(a) 태그 추출
            a_tag = td.find('a')
            if not a_tag: continue
            
            href = a_tag.get('href', '')
            title_text = a_tag.get_text(strip=True)
            
            if href:
                full_url = urljoin(list_url, href)
                
                # 번호 추출 (Subject 바로 앞 td가 보통 번호임)
                # 이전 형제 태그 찾기
                prev_td = td.find_previous_sibling('td')
                no_text = "Link"
                if prev_td:
                    no_text = prev_td.get_text(strip=True)
                
                # 중복 방지
                if not any(l['url'] == full_url for l in links):
                    links.append({
                        "no": no_text,
                        "url": full_url,
                        "title_hint": title_text # 디버깅용
                    })
                    
        return links

    except Exception as e:
        st.error(f"목록 수집 중 오류 발생: {e}")
        return []

# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - app5.py 로직 계승
# ==============================================================================

def scrape_business_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        
        # ★ 인코딩 보정
        response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목
        title = "제목 없음"
        # BoardViewTitle ID 사용
        t_elem = soup.find(id="BoardViewTitle")
        if t_elem: title = t_elem.get_text(strip=True)
        else:
            h = soup.find(['h2', 'h3'])
            if h: title = h.get_text(strip=True)

        # 2. 게시일
        date = "날짜 없음"
        info = soup.find(id="BoardViewAdd")
        if info:
            txt = info.get_text()
            match = re.search(r'등록일\s*:\s*([\d.-]+)', txt)
            if match: date = normalize_date(match.group(1))
            else:
                m2 = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', txt)
                if m2: date = normalize_date(m2.group())

        # 3. 본문 (HTML 보존)
        content_html = ""
        container = soup.find('div', id='BoardContent')
        if container:
            content_html = clean_html_content(container)
        else:
            content_html = "(본문 BoardContent를 찾을 수 없습니다)"

        # 4. 이미지
        images = []
        if container:
            # 원본 soup 재사용 (clean_html_content는 복사본 사용했으므로)
            raw_cont = soup.find('div', id='BoardContent')
            if raw_cont:
                for img in raw_cont.find_all('img'):
                    src = img.get('src', '')
                    if not src: continue
                    
                    if src.startswith('data:image'):
                        try:
                            h, enc = src.split(',', 1)
                            d = base64.b64decode(enc)
                            images.append({"type":"base64", "data":d, "name":"img.png"})
                        except: continue
                    else:
                        if any(x in src for x in ['icon', 'btn', 'blank']): continue
                        full = urljoin(url, src)
                        fname = os.path.basename(full.split('?')[0])
                        if not fname or '.' not in fname: fname = "image.jpg"
                        
                        if not any(d['data'] == full for d in images if d['type']=='url'):
                            images.append({"type":"url", "data":full, "name":fname})

        # 5. 첨부파일 (downloadfile.asp)
        attachments = []
        # 파일 영역이 따로 있거나(BoardViewFile) 본문 근처
        file_area = soup.find(id="BoardViewFile") or soup
        for a in file_area.find_all('a'):
            href = a.get('href', '')
            if 'downloadfile.asp' in href:
                fname = a.get_text(strip=True)
                if fname and fname not in attachments:
                    attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []

# ==============================================================================
# [4] UI 실행
# ==============================================================================

url_input = st.text_input("🔗 경영대학 공지 목록 URL", value="https://ysb.yonsei.ac.kr/board.asp?mid=m06_01")

if st.button("경영대학 공지 수집 시작"):
    if not url_input:
        st.warning("URL을 입력해주세요.")
    else:
        with st.spinner("목록 스캔 중... (td.Subject 필터링)"):
            posts = get_business_notice_links(url_input)
        
        if not posts:
            st.error("게시물을 찾을 수 없습니다. (사이트 구조 확인 필요)")
        else:
            st.success(f"총 {len(posts)}개의 게시물을 발견했습니다.")
            
            progress = st.progress(0)
            for idx, post in enumerate(posts):
                with st.expander(f"[{post['no']}] {post.get('title_hint', '게시물')}"):
                    t, d, c, i, a = scrape_business_detail(post['url'])
                    
                    if t:
                        st.markdown(f"### {t}")
                        st.caption(f"📅 {d} | 🔗 [원본 링크]({post['url']})")
                        
                        st.markdown(c, unsafe_allow_html=True)
                        
                        if i:
                            st.markdown(f"**🖼️ 이미지 ({len(i)}장)**")
                            cols = st.columns(min(len(i), 3))
                            for k, img in enumerate(i):
                                with cols[k%3]:
                                    if img['type'] == 'base64':
                                        st.image(img['data'], use_container_width=True)
                                    else:
                                        st.image(img['data'], use_container_width=True)
                        
                        if a:
                            st.markdown(f"**📎 첨부파일:** {', '.join(a)}")
                    else:
                        st.error("상세 내용을 가져오지 못했습니다.")
                        
                progress.progress((idx + 1) / len(posts))
            
            st.success("수집 완료!")