import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# ================================================================================
# [1] 유틸리티 함수: 영문 날짜 포맷팅 (Feb 19, 2026 -> 2026.02.19)
# ================================================================================
def normalize_uic_date(date_str):
    try:
        months = {
            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
            'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
        }
        
        match = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})', date_str)
        if match:
            m_str, d_str, y_str = match.groups()
            m_num = months.get(m_str[:3].capitalize(), '01')
            return f"{y_str}.{m_num}.{d_str.zfill(2)}"
            
        match_kr = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match_kr:
            y, m, d = match_kr.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
            
        return date_str
    except:
        return date_str

# ================================================================================
# [2] UIC 리스트 페이지 크롤링 엔진 (카테고리별 상위 5개 추출)
# ================================================================================
def get_uic_links(url):
    """UIC 메인 페이지의 divbox_half_news 박스 3개에서 각각 상위 5개의 링크를 추출합니다."""
    links = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 사진에서 확인한 3개의 half box 모두 찾기
        half_boxes = soup.find_all('div', class_='divbox_half_news')
        
        idx = 1 # 가상의 글 번호 (화면 표시용)
        
        for box in half_boxes:
            # 1. 카테고리 이름 추출 (예: Academic Affairs)
            category_span = box.find('span', class_='Text_26bk')
            category = category_span.get_text(strip=True) if category_span else "Notice"
            
            # 2. 박스 안의 뉴스 컨테이너 찾기
            newsbox = box.find('div', class_='newsbox')
            if not newsbox: continue
            
            # 3. a 태그 찾기 (상위 5개만 제한)
            a_tags = newsbox.find_all('a')
            count = 0
            
            for a in a_tags:
                if count >= 5: # 5개를 꽉 채웠으면 다음 박스로 넘어감
                    break
                    
                href = a.get('href')
                if not href: continue
                
                full_url = urljoin(url, href)
                title = a.get_text(strip=True)
                
                # 빈 링크나 "more" 같은 버튼 제외
                if not title or title.lower() == 'more':
                    continue

                links.append({
                    "no": str(idx),
                    "title": f"[{category}] {title}", # 보기 좋게 카테고리 달아주기
                    "url": full_url
                })
                idx += 1
                count += 1
                
        return links
    except Exception as e:
        print(f"목록 수집 에러: {e}")
        return []

# ================================================================================
# [3] UIC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_uic_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = "제목 없음"
        title_div = soup.find('div', id='BoardViewTitle')
        if title_div:
            title = title_div.get_text(strip=True)

        date = "날짜 없음"
        attachments = []
        
        board_adds = soup.find_all('div', id='BoardViewAdd')
        for b_add in board_adds:
            text_content = b_add.get_text(strip=True)
            
            if 'Views:' in text_content or re.search(r'[A-Za-z]+\s+\d{1,2},\s+\d{4}', text_content):
                date = normalize_uic_date(text_content)
                
            a_tags = b_add.find_all('a')
            for a in a_tags:
                img = a.find('img')
                if img:
                    fname = a.get_text(separator=' ', strip=True).strip('"').strip()
                    fname = re.sub(r'\([\d.,]+\s*(KB|MB|GB|Bytes?)\)', '', fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        content_html = ""
        images = []
        
        content_div = soup.find('div', id='BoardContent')
        
        if content_div:
            for idx, img in enumerate(content_div.find_all('img')):
                src = img.get('src', '')
                if src and not any(x in src for x in ['icon', 'btn', 'blank', 'ext_']):
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

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면 (공통 UI 포맷 적용)
# ================================================================================
st.set_page_config(page_title="UIC 공지 리스트 크롤러", layout="wide")
st.title("🌍 언더우드국제대학(UIC) 공지사항 추출기")
st.markdown("UIC 뉴스 대시보드에서 **각 카테고리별 상위 5개**의 게시물을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: center; }
th { background-color: #f8f9fa; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# UIC 공지 메인 페이지 URL
list_url_input = st.text_input("🔗 UIC 공지사항 **목록(List)** URL", value="https://uic.yonsei.ac.kr/main/news.php?mid=m06_01_02")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner('UIC 게시물 목록 스캔 중... (각 카테고리별 상위 5개)'):
            post_links = get_uic_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 게시판 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 최신 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행 (Progress bar 적용)
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"#{item['no']} {item['title']}", expanded=True):
                    # UIC 전용 상세 크롤링 함수 호출
                    title, date, content, images, attachments = scrape_uic_detail(item['url'])
                    
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