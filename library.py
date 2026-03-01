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
# [2] 연세대 도서관 리스트(List) 페이지 크롤링 엔진 (★ 10개 제한 추가)
# ================================================================================
def get_library_links(list_url):
    """상단 고정 공지를 제외한 일반 게시물 링크를 최대 10개까지 수집합니다."""
    links = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(list_url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 모든 tr 태그 탐색
        rows = soup.find_all('tr')
        
        count = 0  # 💡 수집된 게시물 개수를 세는 변수
        
        for row in rows:
            # ★ 10개를 모두 찾았으면 반복문 종료
            if count >= 10:
                break
                
            # 상단 고정 공지(<tr class="always">) 제외
            row_classes = row.get('class', [])
            if 'always' in row_classes:
                continue

            # 1. 링크(a 태그) 찾기
            a_tag = row.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href')
            if not href or href == '#' or 'javascript:' in href:
                continue
                
            full_url = urljoin(list_url, href)
            
            # 2. 제목 추출
            title = a_tag.get_text(separator=' ', strip=True)
            if not title:
                continue
            
            # 3. 글 번호 추출
            num_text = "일반"
            tds = row.find_all('td')
            if tds:
                num_text = tds[0].get_text(strip=True)
                
            # 중복 데이터 삽입 방지
            if not any(d['url'] == full_url for d in links):
                links.append({
                    "no": num_text,
                    "title": title,
                    "url": full_url
                })
                count += 1  # 💡 성공적으로 수집할 때마다 카운트 1 증가
                
        return links
        
    except Exception as e:
        st.error(f"목록을 수집하는 중 에러가 발생했습니다: {e}")
        return []

# ================================================================================
# [3] 연세대 도서관 상세 페이지 크롤링 엔진
# ================================================================================
def scrape_library_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 및 2. 날짜 추출 (<div class="boardInfo">)
        title = "제목 없음"
        date = "날짜 없음"
        
        board_info = soup.find('div', class_='boardInfo')
        if board_info:
            info_text = board_info.get_text(separator=' ', strip=True)
            
            date_match = re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', info_text)
            if date_match:
                date = normalize_date(date_match.group())
                
            title_tag = board_info.find(['h2', 'h3', 'h4', 'strong'])
            if title_tag:
                title = title_tag.get_text(strip=True)
            else:
                if date_match:
                    title = info_text.split(date_match.group())[0].strip()
                else:
                    title = info_text

        # 3. 본문 및 4. 이미지 추출 (<div class="boardContent">)
        content_html = ""
        images = []
        
        board_content = soup.find('div', class_='boardContent')
        
        if board_content:
            for idx, img in enumerate(board_content.find_all('img')):
                src = img.get('src', '')
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
                        
                        unquoted_path = urllib.parse.unquote(parsed.path)
                        encoded_path = urllib.parse.quote(unquoted_path)
                        
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(unquoted_path)
                        
                        if not any(d.get('data') == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                
                img.decompose()
                
            for table in board_content.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            
            content_html = board_content.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출 (<div class="additionalItems">)
        attachments = []
        additional_items = soup.find('div', class_='additionalItems')
        if additional_items:
            for a_tag in additional_items.find_all('a'):
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
st.set_page_config(page_title="연세 도서관 공지 크롤러", layout="wide")
st.title("📚 연세대학교 도서관 공지사항 추출기")
st.markdown("**목록 페이지**를 입력하면 상단 고정 공지를 제외하고 **최대 10개**의 일반 게시물을 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: left; }
th { background-color: #f8f9fa; font-weight: bold; text-align: center; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# 도서관 공지사항 URL
list_url_input = st.text_input("🔗 연세 도서관 **목록(List)** URL", value="https://library.yonsei.ac.kr/bbs/list/1?pn=1")

if st.button("최신 공지사항 10개 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner("도서관 게시물 목록 스캔 중... (최대 10개 수집)"):
            post_links = get_library_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 사이트 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 일반 게시물을 수집했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행 (Progress bar 적용)
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"[{item['no']}] {item['title']}", expanded=True):
                    # 도서관 전용 상세 크롤링 함수 호출
                    title, date, content, images, attachments = scrape_library_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### {title}")
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