import os
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import timedelta, datetime
import time
import pytz
import json
from st_aggrid import AgGrid, GridOptionsBuilder
from collections import defaultdict
from urllib.parse import unquote
from cryptography.fernet import Fernet

# -------------------------------------------------------------------------------
# 기본 설정 및 시간 관련 설정
# -------------------------------------------------------------------------------
korea_tz = pytz.timezone("Asia/Seoul")
today_date = datetime.now(korea_tz)
current_year = today_date.year
current_month = today_date.month

# -------------------------------------------------------------------------------
# GitHub 초기화 및 커밋 관련 함수
# -------------------------------------------------------------------------------
schedules_root_dir = "team_schedules"
model_example_root_dir = "team_model_example"
today_schedules_root_dir = "team_today_schedules"  # 매일 근무자 dir 생성
memo_root_dir = "team_memo"

def git_init_repo():
    """Git 저장소 초기화 및 원격 연결"""
    if not os.path.exists(schedules_root_dir):
        os.makedirs(schedules_root_dir, exist_ok=True)
        os.system(f'cd {schedules_root_dir} && git init')
        os.system(f'cd {schedules_root_dir} && git remote add origin {st.secrets["GITHUB"]["REPO_URL"]}')

def git_auto_commit(file_path, team_name):
    """변경사항 자동 커밋"""
    commit_message = f"Auto-commit: {team_name} {datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M')}"
    os.system(f'cd {schedules_root_dir} && git add {file_path}')
    os.system(f'cd {schedules_root_dir} && git commit -m "{commit_message}"')
    os.system(f'cd {schedules_root_dir} && git push origin main')

def git_pull_changes():
    """최신 변경사항 동기화"""
    os.system(f'cd {schedules_root_dir} && git pull origin main')

def handle_git_conflicts():
    """충돌 자동 해결"""
    conflicts = os.popen(f'cd {schedules_root_dir} && git diff --name-only --diff-filter=U').read()
    if conflicts:
        st.warning("충돌 감지! 자동 해결 시도 중...")
        os.system(f'cd {schedules_root_dir} && git checkout --theirs .')
        git_auto_commit(conflicts, "Conflict Resolution")
        st.experimental_rerun()

def encrypt_data(data):
    """데이터 암호화 예시 함수"""
    cipher = Fernet(st.secrets["CRYPTO"]["KEY"])
    return cipher.encrypt(data.encode())

# -------------------------------------------------------------------------------
# 디렉토리 생성 함수
# -------------------------------------------------------------------------------
def create_dir_safe(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        st.write(f"{path} 디렉토리 생성 완료")

for d in [schedules_root_dir, model_example_root_dir, today_schedules_root_dir, memo_root_dir]:
    create_dir_safe(d)

# GitHub 저장소 초기화 및 동기화
git_init_repo()
git_pull_changes()
if 'git_synced' not in st.session_state:
    git_pull_changes()
    st.session_state.git_synced = True

# 주기적 Git 동기화 (10분 간격)
if (datetime.now() - st.session_state.get('last_sync', datetime.now())).seconds > 600:
    git_pull_changes()
    st.session_state.last_sync = datetime.now()
  
# -------------------------------------------------------------------------------
# 앱 기본 타이틀 및 사이드바 설정
# -------------------------------------------------------------------------------
st.title("Rotation Scheduler WebService 💻")
st.sidebar.title("팀 선택 ✅")
teams = ["관제SO팀", "동부SO팀", "보라매SO팀", "백본SO팀", "보안SO팀", "성수SO팀", "중부SO팀"]
selected_team = st.sidebar.radio("", teams)

months = [f"{i}월" for i in range(1, 13)]
if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = today_date.date()
if "selected_month" not in st.session_state:
    st.session_state["selected_month"] = f"{today_date.month}월"

def update_date_from_month():
    new_month_num = int(st.session_state["selected_month"].replace("월", ""))
    st.session_state["selected_date"] = datetime(current_year, new_month_num, 1).date()

def update_month_from_date():
    st.session_state["selected_month"] = f"{st.session_state['selected_date'].month}월"

st.sidebar.title("월 선택 📅")
st.sidebar.selectbox(
    "",
    options=months,
    key="selected_month",
    on_change=update_date_from_month
)

# -------------------------------------------------------------------------------
# 폴더 경로 설정
# -------------------------------------------------------------------------------
schedules_folder_path = os.path.join(schedules_root_dir, selected_team)
model_example_folder_path = os.path.join(model_example_root_dir, selected_team)
today_team_folder_path = os.path.join(today_schedules_root_dir, selected_team)
memo_team_folder_path = os.path.join(memo_root_dir, selected_team)

for folder in [schedules_folder_path, model_example_folder_path, today_team_folder_path, memo_team_folder_path]:
    create_dir_safe(folder)

selected_month_num = int(st.session_state["selected_month"].replace("월", ""))
start_date = datetime(current_year, selected_month_num, 1)
end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)
date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

# -------------------------------------------------------------------------------
# 메모 추가 관련
# -------------------------------------------------------------------------------
st.sidebar.title("메모 추가 ✏️")
if 'new_memo_text' not in st.session_state:
    st.session_state.new_memo_text = ""
if 'author_name' not in st.session_state:
    st.session_state.author_name = ""

def get_korea_time():
    return datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M:%S')

def save_memo_with_reset(memo_file_path, memo_text, author=""):
    memo_data = {
        "note": memo_text,
        "author": author,
        "timestamp": get_korea_time()
    }
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            memos_list = json.load(f)
    else:
        memos_list = []

    for existing_memo in memos_list:
        if (existing_memo["note"] == memo_data["note"] and
            existing_memo["author"] == memo_data["author"] and
            existing_memo["timestamp"] == memo_data["timestamp"]):
            st.write("메모가 중복되었습니다. 저장이 취소됩니다.")
            return

    memos_list.append(memo_data)
    with open(memo_file_path, "w", encoding="utf-8") as f:
        json.dump(memos_list, f, ensure_ascii=False, indent=4)

def save_and_reset():
    if st.session_state.new_memo_text.strip():
        save_memo_with_reset(
            os.path.join(memo_team_folder_path, f"{current_year}_{st.session_state['selected_month']}_memos.json"),
            st.session_state.new_memo_text.strip(),
            author=st.session_state.author_name
        )
        st.session_state.new_memo_text = ""
        st.write("메모가 저장되었습니다!")
    else:
        st.write("빈 메모는 저장할 수 없습니다!")
        
st.sidebar.text_input(
    "작성자 이름",
    placeholder="작성자 이름을 입력하세요...",
    key="author_name"
)
st.sidebar.text_area(
    "메모 내용",
    placeholder="여기에 메모를 입력하세요...",
    key="new_memo_text"
)
st.sidebar.button("메모 저장", on_click=save_and_reset)

# -------------------------------------------------------------------------------
# 관리자 로그인 및 파일 업로드 관련 (생략 가능한 부분)
# -------------------------------------------------------------------------------
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

st.sidebar.title("관리자 로그인 🔒")
password = st.sidebar.text_input("비밀번호 입력 🔑", type="password")

if password:
    correct_password = st.secrets["teams"].get(selected_team)
    if password == correct_password:
        st.session_state.admin_authenticated = True
        st.sidebar.success(f"{selected_team} 관리자 모드 활성화 ✨")
        # 근무표 파일 업로드 처리 (생략: 위 paste.txt 소스 참조)
        # 범례 파일 업로드 처리 (생략)
    else:
        st.sidebar.error("❌ 비밀번호 오류 ❌")
st.sidebar.markdown("🙋:문의 : 관제SO팀")

# -------------------------------------------------------------------------------
# 기본 근무표 및 작업 테이블 출력
# -------------------------------------------------------------------------------
schedules_file_path = os.path.join(schedules_folder_path, f"{current_year}_{st.session_state['selected_month']}_{selected_team}_schedule.csv")
model_example_file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
memo_file_path = os.path.join(memo_team_folder_path, f"{current_year}_{st.session_state['selected_month']}_memos.json")

try:
    df = pd.read_csv(schedules_file_path)
    if st.session_state["selected_date"].month == current_month:
        default_date = today_date
    else:
        default_date = datetime(current_year, selected_month_num, 1)

    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.header(f"{selected_team} {st.session_state['selected_month']} 근무표")
    with col2:
        buffer = BytesIO()
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
        buffer.seek(0)
        st.download_button(
            label="📊 엑셀 다운로드",
            data=buffer,
            file_name=f"{selected_team}_{st.session_state['selected_month']}_근무표.csv",
            mime="text/csv"
        )

    # 근무표 데이터 처리
    df_schedule = pd.read_csv(schedules_file_path)
    df_model = pd.read_csv(model_example_file_path)
    df_model = df_model.dropna(subset=["실제 근무", "팀 근무기호"])
    work_mapping = dict(zip(df_model["팀 근무기호"], df_model["실제 근무"]))

    # 날짜 선택 위젯
    st.subheader("날짜 선택 📅")
    selected_date = st.date_input(
        "날짜를 선택하세요:",
        key="selected_date",
        on_change=update_month_from_date
    )
    today_column = f"{selected_date.day}({['월','화','수','목','금','토','일'][selected_date.weekday()]})"
    df_schedule.columns = df_schedule.columns.str.strip()

    if today_column in df_schedule.columns:
        df_schedule["근무 형태"] = df_schedule[today_column].map(work_mapping).fillna("")
        # 주간, 야간, 휴가 근무자 분리 및 정렬
        day_shift = df_schedule[df_schedule["근무 형태"].str.contains("주", na=False)].copy()
        night_shift = df_schedule[df_schedule["근무 형태"].str.contains("야", na=False)].copy()
        vacation_keywords = ["휴가(주)", "대휴(주)", "대휴", "경조", "연차", "야/연차", "숙/연차"]
        vacation_shift = df_schedule[df_schedule[today_column].isin(vacation_keywords)].copy()
        
        # 화면 출력 (팀장, 부서별 정렬 등)
        st.subheader(f"{selected_date.strftime('%Y-%m-%d')} {selected_team} 근무자 📋")
        col_day, col_night = st.columns(2)
        with col_day:
            st.write("주간 근무자 ☀️")
            if not day_shift.empty:
                for part in day_shift["파트 구분"].unique():
                    part_group = day_shift[day_shift["파트 구분"] == part]
                    part_display = part_group[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"})
                    part_display["파트"] = part_display["파트"].replace("총괄", "팀장")
                    part_display.index = ['🌇'] * len(part_display)
                    st.table(part_display)
            else:
                st.write("주간 근무자가 없습니다.")
        with col_night:
            st.write("야간 근무자 🌙")
            if not night_shift.empty:
                for part in night_shift["파트 구분"].unique():
                    part_group = night_shift[night_shift["파트 구분"] == part]
                    part_display = part_group[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"})
                    part_display["파트"] = part_display["파트"].replace("총괄", "팀장")
                    part_display.index = ['🌃'] * len(part_display)
                    st.table(part_display)
            else:
                st.write("야간 근무자가 없습니다.")
            st.write("휴가 근무자 🌴")
            if not vacation_shift.empty:
                vacation_display = vacation_shift[["파트 구분", "이름", today_column]].rename(
                    columns={"파트 구분": "파트", today_column: "근무"})
                vacation_display["파트"] = vacation_display["파트"].replace("총괄", "팀장")
                vacation_display.index = ['🌄'] * len(vacation_display)
                st.table(vacation_display)
            else:
                st.write("휴가 근무자가 없습니다.")
                
    else:
        st.warning(f"선택한 날짜 ({today_column})에 해당하는 데이터가 없습니다.")

    # 전체 근무표 출력 (AgGrid 활용)
    exclude_columns = ['본부 구분', '팀 구분', '년/월', '근무 구분']
    filtered_df = df.drop(columns=[col for col in exclude_columns if col in df.columns], errors='ignore')
    gb = GridOptionsBuilder.from_dataframe(filtered_df)
    gb.configure_column("파트 구분", pinned="left")
    gb.configure_column("이름", pinned="left")
    gb.configure_default_column(width=10)
    gb.configure_grid_options(domLayout='normal', alwaysShowHorizontalScroll=True, suppressColumnVirtualisation=True)
    grid_options = gb.build()
    st.subheader("전체 근무표 📆")
    AgGrid(
        filtered_df,
        gridOptions=grid_options,
        height=555,
        theme="streamlit"
    )
    
    st.subheader("🔍 구성원 근무표 검색")
    employee_name = st.text_input(f"{selected_team} 구성원 이름 입력")
    if employee_name:
        filtered_emp = df[df["이름"].str.contains(employee_name, na=False)]
        if not filtered_emp.empty:
            st.write(f"{employee_name} 님의 근무표")
            st.dataframe(filtered_emp, hide_index=True)
        else:
            st.warning(f"'{employee_name}' 님의 데이터가 없습니다.")
except FileNotFoundError:
    st.error("❌ 근무표 파일이 등록되지 않았습니다.")
except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")

# 메모 출력 부분
st.header(f"{selected_team} - {st.session_state['selected_month']} 메모 📓")
def load_memos(memo_file_path):
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

memos_list = load_memos(memo_file_path)
if memos_list:
    for idx, memo in enumerate(reversed(memos_list)):
        timestamp_obj = datetime.strptime(memo['timestamp'], '%Y-%m-%d %H:%M:%S')
        formatted_timestamp = timestamp_obj.strftime('%Y-%m-%d %H:%M')
        st.markdown(f"📢 **{memo['author']}**님 ({formatted_timestamp})")
        st.write(memo["note"].replace("\n", "  \n"))
        if st.button(
            f"🙋 삭제는 관리자에게 문의 부탁드립니다! (작성자: {memo['author']} / 작성시간: {formatted_timestamp})",
            key=f"delete_{formatted_timestamp}_{idx}",
            disabled=not st.session_state.admin_authenticated
        ):
            # 관리자 인증이 되어 있으면 삭제 동작
            with open(memo_file_path, "r", encoding="utf-8") as f:
                current_memos = json.load(f)
            updated_memos = [m for m in current_memos if m['timestamp'] != memo['timestamp']]
            with open(memo_file_path, "w", encoding="utf-8") as f:
                json.dump(updated_memos, f, ensure_ascii=False, indent=4)
            st.write("메모가 삭제되었습니다!")
            time.sleep(1)
            st.experimental_rerun()
        st.markdown("---")
else:
    st.info(f"{selected_team}의 {st.session_state['selected_month']}에 저장된 메모가 없습니다.")

# -------------------------------------------------------------------------------
# API 관련 함수 및 헬퍼 함수
# -------------------------------------------------------------------------------
def get_json_file_path(date_str, team):
    today_team_path = os.path.join(today_schedules_root_dir, team)
    month_folder = os.path.join(today_team_path, date_str[:7])
    json_file_path = os.path.join(month_folder, f"{date_str}_schedule.json")
    return json_file_path

def load_json_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def validate_date_format(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def get_json_file_path(date_str, team):
    # 실제 환경에 맞게 경로 설정
    today_team_path = os.path.join("team_today_schedules", team)
    month_folder = os.path.join(today_team_path, date_str[:7])
    json_file_path = os.path.join(month_folder, f"{date_str}_schedule.json")
    return json_file_path

def load_json_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def api_handler():
    query_params = st.experimental_get_query_params()
    team_values = query_params.get("team")
    date_values = query_params.get("date")
    if not team_values or not date_values:
        st.write({"status": "error", "message": "team 과 date 파라미터가 필요합니다."})
        return

    # URL 인코딩된 값 복원
    selected_team = unquote(team_values)
    selected_date = unquote(date_values)
    
    # 날짜 형식 검사
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        st.write({"status": "error", "message": "날짜 형식은 YYYY-MM-DD 이어야 합니다."})
        return

    json_file_path = get_json_file_path(selected_date, selected_team)
    schedule_data = load_json_data(json_file_path)
    if schedule_data:
        json_str = json.dumps({"data": schedule_data}, ensure_ascii=False, indent=2)
        st.markdown(f"<pre>{json_str}</pre>", unsafe_allow_html=True)
    else:
        st.write({"status": "error", "message": f"{selected_date} ({selected_team})에 해당하는 데이터를 찾을 수 없습니다."})

def main_app():
    st.write("메인 앱 실행 중입니다.")

if __name__ == "__main__":
    params = st.experimental_get_query_params()
    if "team" in params and "date" in params:
        api_handler()
    else:
        main_app()
