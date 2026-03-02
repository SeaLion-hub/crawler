import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# 보기 싫은 SSL 경고 메시지 숨기기
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================================================================================
# [1] 유틸리티 함수: 날짜 정규화
# ================================================================================
def normalize_date(date_str):
    """문자열에서 YYYY.MM.DD 형식만 추출하여 통일합니다."""
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        return date_str

# ================================================================================
# [2] 연세대 국제처 리스트(List) 페이지 크롤링 엔진
# ================================================================================
def get_international_links(list_url):
    """<li class="img"> 또는 <li class="no_img">로 감싸진 링크를 수집합니다."""
    links = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(list_url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 'img' 또는 'no_img' 클래스를 가진 모든 li 태그 탐색
        items = soup.find_all('li', class_=lambda c: c and c in ['img', 'no_img'])
        
        for idx, item in enumerate(items):
            # 1. 링크(a 태그) 찾기
            a_tag = item.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href', '')
            if not href or href == '#' or 'javascript:' in href:
                continue
                
            full_url = urljoin(list_url, href)
            
            # 2. 제목 추출
            title_elem = item.find(['strong', 'h3', 'h4']) or item.find(class_=lambda c: c and 'title' in c)
            if title_elem:
                title = title_elem.get_text(strip=True)
            else:
                title = a_tag.get_text(separator=' ', strip=True)
                
            if not title:
                continue
            
            # 3. 글 번호 부여
            num_elem = item.find(class_=lambda c: c and 'num' in c)
            num_text = num_elem.get_text(strip=True) if num_elem else str(idx + 1)
                
            # 중복 데이터 삽입 방지
            if not any(d['url'] == full_url for d in links):
                links.append({
                    "no": num_text,
                    "title": title,
                    "url": full_url
                })
                
        return links
        
    except Exception as e:
        st.error(f"목록을 수집하는 중 에러가 발생했습니다: {e}")
        return []

# ================================================================================
# [3] 연세대 국제처 상세 페이지 크롤링 엔진
# ================================================================================
def scrape_international_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 추출 (★ 수정됨: <li class="title_view"> 안의 <h4> 만 타격)
        title = "제목 없음"
        title_li = soup.find('li', class_='title_view')
        if title_li:
            h4_tag = title_li.find('h4')
            if h4_tag:
                title = h4_tag.get_text(strip=True)
            else:
                # 플랜 B: h4 태그가 없는 구조일 경우, 날짜/조회수가 섞이지 않게 info_txt를 먼저 날려버림
                temp_li = BeautifulSoup(str(title_li), 'html.parser')
                info = temp_li.find('div', class_='info_txt')
                if info:
                    info.decompose()
                title = temp_li.get_text(strip=True)

        # 2. 날짜 추출 (<div class="info_txt"> 내의 <span class="date_txt"> 타격)
        date = "날짜 없음"
        info_div = soup.find('div', class_='info_txt')
        if info_div:
            date_span = info_div.find('span', class_='date_txt')
            if date_span:
                date = normalize_date(date_span.get_text(strip=True))
            else:
                info_text = info_div.get_text(separator=' ', strip=True)
                date_match = re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', info_text)
                if date_match:
                    date = normalize_date(date_match.group())

        # 3. 본문 및 4. 이미지 추출 (<div class="view_contents">)
        content_html = ""
        images = []
        
        content_div = soup.find('div', class_='view_contents')
        
        if content_div:
            for idx, img in enumerate(content_div.find_all('img')):
                src = img.get('src', '')
                if not src:
                    continue
                    
                if src.startswith('data:image'):
                    try:
                        header, encoded = src.split(',', 1)
                        data = base64.b64decode(encoded)
                        ext = "png"
                        if "jpeg" in header or "jpg" in header: ext = "jpg"
                        images.append({"type": "base64", "data": data, "name": f"image_{idx+1}.{ext}"})
                    except Exception: 
                        pass
                else:
                    full_url = urljoin(url, src) 
                    parsed = urllib.parse.urlparse(full_url)
                    
                    # 로컬 파일(file://) 등 비정상 웹 링크 필터링
                    if parsed.scheme not in ['http', 'https']:
                        img.decompose()
                        continue
                    
                    unquoted_path = urllib.parse.unquote(parsed.path)
                    encoded_path = urllib.parse.quote(unquoted_path)
                    
                    safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                    fname = os.path.basename(unquoted_path)
                    
                    if not any(d.get('data') == safe_url for d in images):
                        images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                
                img.decompose()
                
            for table in content_div.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출 (<div class="file_txt">)
        attachments = []
        file_divs = soup.find_all('div', class_='file_txt')
        for file_div in file_divs:
            for a_tag in file_div.find_all('a'):
                href = a_tag.get('href', '')
                if href and not href.startswith('#') and 'javascript' not in href:
                    fname = a_tag.get_text(separator=' ', strip=True).strip()
                    fname = re.sub(r'\([\d.,]+\s*(KB|MB|GB|Bytes?)\)', '', fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면
# ================================================================================
st.set_page_config(page_title="연세 국제처 공지 크롤러", layout="wide")
st.title("🌐 연세대학교 국제처 공지사항 추출기")
st.markdown("**목록 페이지**를 입력하면 이미지(`img`) 및 텍스트(`no_img`) 카드 형태의 모든 게시물을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: left; }
th { background-color: #f8f9fa; font-weight: bold; text-align: center; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# 국제처 공지사항 URL
list_url_input = st.text_input("🔗 연세 국제처 **목록(List)** URL", value="https://oia.yonsei.ac.kr/news/newsIMain.asp")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner("국제처 게시물 목록 스캔 중... (img / no_img 탐색)"):
            post_links = get_international_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 사이트 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행 (Progress bar 적용)
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"[{item['no']}] {item['title']}", expanded=True):
                    title, date, content, images, attachments = scrape_international_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        # 본문
                        st.markdown(content, unsafe_allow_html=True)
                        
                        # 이미지 (★ 로컬 이미지/손상된 이미지 에러 시 무시하는 안전장치 적용)
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3) if len(images) > 0 else 1)
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    try:
                                        st.image(img_item['data'], caption=img_item['name'], use_container_width=True)
                                    except Exception:
                                        pass
                        
                        # 첨부파일 (줄바꿈 나열)
                        if attachments:
                            st.markdown("**📎 첨부파일:**\n" + "\n".join([f"- {att}" for att in attachments]))
                    else:
                        st.error("내용 추출 실패")
                
                # 진행률 업데이트
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")