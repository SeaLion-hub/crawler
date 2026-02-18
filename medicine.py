import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString, Comment, Tag
import base64
import re
import os
from urllib.parse import urljoin, urlparse, urlunparse

# --- 페이지 설정 (의대 전용) ---
st.set_page_config(page_title="연세 의과대학 공지 크롤러", layout="wide")
st.title("🏥 연세 의과대학 공지사항 추출기 (독립형)")
st.markdown("목록(`bbs-item`) 감지 + 본문(`fr-view`) + 표 보존 + 첨부파일 자동 수집")

# --- [스타일] CSS ---
st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: center; }
th { background-color: #f8f9fa; font-weight: bold; }
.fr-view { font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================

def normalize_date(date_str):
    """날짜 문자열을 YYYY.MM.DD로 표준화"""
    try:
        clean = re.sub(r'[년월일/-]', '.', date_str)
        parts = [p.strip() for p in clean.split('.') if p.strip().isdigit()]
        if len(parts) >= 3:
            y, m, d = parts[:3]
            if len(y) == 2: y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except: return date_str

def clean_html_content(element):
    """HTML 본문 정제 (스크립트 제거, 표 보존)"""
    import copy
    element = copy.copy(element)
    
    # 보안상 제거
    for tag in element.find_all(['script', 'style', 'noscript', 'iframe', 'img']):
        tag.decompose()
        
    # 표 테두리 강제 적용
    for table in element.find_all('table'):
        if not table.get('border'): table['border'] = "1"
        
    return element.decode_contents().strip()

# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler) - 수정됨
# ==============================================================================

def get_medicine_notice_links(list_url):
    """
    게시판 목록에서 'bbs-item' 클래스를 가진 요소들의 링크를 수집합니다.
    (페이지네이션 버튼 전까지만 수집하는 효과)
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(list_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        
        # ★ 핵심 수정: 주석 대신 'bbs-item' 클래스를 직접 타격
        # 스크린샷 분석 결과, 각 게시물은 <div class="bbs-item ..."> 안에 있음
        items = soup.find_all('div', class_='bbs-item')
        
        if not items:
            # 혹시 모를 예비책: bbs-list 클래스나 일반적인 리스트 구조 확인
            items = soup.select('.bbs-list li') or soup.select('tbody tr')

        for item in items:
            # 링크(a 태그) 찾기
            a_tag = item.find('a')
            if not a_tag: continue
            
            href = a_tag.get('href', '')
            
            # 유효한 게시물 링크인지 검증 (articleNo 또는 mode=view 포함 여부)
            if 'articleNo' in href or 'mode=view' in href:
                full_url = urljoin(list_url, href)
                
                # 번호 추출 시도 (없으면 Post)
                # bbs-item 구조상 번호가 명시적으로 없을 수도 있음. 
                # 텍스트 전체에서 숫자를 찾거나 'Notice' 등을 찾음
                text_content = item.get_text(strip=True)
                no_text = "Post" 
                
                # 중복 방지
                if not any(l['url'] == full_url for l in links):
                    links.append({"no": no_text, "url": full_url})

        return links

    except Exception as e:
        st.error(f"목록 수집 중 오류 발생: {e}")
        return []

# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - 기존 유지
# ==============================================================================

def scrape_medicine_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목
        title = "제목 없음"
        header = soup.find(class_="article-header")
        if header:
            # h1~h4 중 하나
            t_tag = header.find(['h1', 'h2', 'h3', 'h4'])
            if t_tag: title = t_tag.get_text(strip=True)
            else: title = header.get_text(strip=True)
            
        # 2. 게시일
        date = "날짜 없음"
        # 헤더 텍스트 전체에서 날짜 패턴 검색
        d_text = header.get_text() if header else soup.get_text()
        d_match = re.search(r'\d{4}[.-]\s*\d{1,2}[.-]\s*\d{1,2}', d_text)
        if d_match: date = normalize_date(d_match.group())

        # 3. 본문 (HTML 구조 보존)
        content_html = ""
        fr_view = soup.find('div', class_='fr-view')
        
        if fr_view:
            # 주석(키워드/태그) 기준으로 뒷부분 잘라내기
            end_comment = fr_view.find(string=lambda t: isinstance(t, Comment) and "키워드/태그" in t)
            if end_comment:
                # 주석부터 뒤의 형제들 모두 삭제
                curr = end_comment
                while curr:
                    nxt = curr.next_sibling
                    curr.extract()
                    curr = nxt
            
            # HTML 정제 (이미지 제거, 표 보존)
            content_html = clean_html_content(fr_view)
        else:
            content_html = "(본문 영역 .fr-view를 찾을 수 없습니다)"

        # 4. 이미지 (본문에서 추출)
        images = []
        if fr_view:
            # 원본 soup에서 이미지 태그 탐색 (clean_html_content는 복사본을 썼으므로)
            # 안전하게 다시 찾기
            raw_view = soup.find('div', class_='fr-view')
            if raw_view:
                for img in raw_view.find_all('img'):
                    src = img.get('src', '')
                    if not src: continue
                    
                    if src.startswith('data:image'):
                        try:
                            head, enc = src.split(',', 1)
                            data = base64.b64decode(enc)
                            ext = "png"
                            if "jpeg" in head: ext = "jpg"
                            images.append({"type":"base64", "data":data, "name":f"img.{ext}"})
                        except: continue
                    else:
                        if any(x in src for x in ['icon', 'btn', 'blank']): continue
                        full_url = urljoin(url, src)
                        fname = os.path.basename(full_url.split('?')[0])
                        if not fname or '.' not in fname: fname = "image.jpg"
                        
                        # 중복 방지
                        if not any(d['data'] == full_url for d in images if d['type']=='url'):
                            images.append({"type":"url", "data":full_url, "name":fname})

        # 5. 첨부파일
        attachments = []
        attach_div = soup.find('div', class_='attach-files')
        if attach_div:
            for a in attach_div.find_all('a'):
                href = a.get('href', '')
                # 다운로드 링크 식별
                if 'download' in href or 'mode=download' in href:
                    fname = a.get_text(strip=True)
                    if fname and fname not in attachments:
                        attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []

# ==============================================================================
# [4] UI (실행부)
# ==============================================================================

url_input = st.text_input("🔗 의과대학 공지 목록 URL", value="https://medicine.yonsei.ac.kr/medicine/news/notice.do")

if st.button("의과대학 공지 수집 시작"):
    if not url_input:
        st.warning("URL을 입력해주세요.")
    else:
        with st.spinner("목록 스캔 중... (bbs-item 감지)"):
            posts = get_medicine_notice_links(url_input)
        
        if not posts:
            st.error("게시물을 찾을 수 없습니다. (사이트 구조가 예상과 다릅니다)")
        else:
            st.success(f"총 {len(posts)}개의 게시물을 발견했습니다.")
            
            progress = st.progress(0)
            for idx, post in enumerate(posts):
                with st.expander(f"게시물 {idx+1} 상세 보기"):
                    t, d, c, i, a = scrape_medicine_detail(post['url'])
                    
                    if t:
                        st.markdown(f"### {t}")
                        st.caption(f"📅 {d} | 🔗 [원본 링크]({post['url']})")
                        
                        # HTML 본문 렌더링
                        st.markdown(c, unsafe_allow_html=True)
                        
                        # 이미지
                        if i:
                            st.markdown(f"**🖼️ 이미지 ({len(i)}장)**")
                            cols = st.columns(min(len(i), 3))
                            for k, img in enumerate(i):
                                with cols[k%3]:
                                    if img['type'] == 'base64':
                                        st.image(img['data'], use_container_width=True)
                                    else:
                                        st.image(img['data'], use_container_width=True)
                        
                        # 첨부파일
                        if a:
                            st.markdown(f"**📎 첨부파일:** {', '.join(a)}")
                    else:
                        st.error("상세 내용을 가져오지 못했습니다.")
                        
                progress.progress((idx + 1) / len(posts))
            
            st.success("수집 완료!")