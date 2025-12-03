from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import calendar            
import config
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = config.secret_key  # 세션 암호화에 필요 (아무거나 입력 가능)

# 1. 데이터베이스 연결 설정 
DB_HOST = "localhost"
DB_PORT = config.DB_PORT
DB_NAME = "alba2025"    
DB_USER = "db2025"    
DB_PASS = config.DB_PASSWORD       

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )
    return conn

# 2. 메인 페이지 (로그인 화면)
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        
        # SFW: DB에서 이메일과 비밀번호가 일치하는 사용자 찾기
        cur.execute("SELECT user_id, name, email FROM \"User\" WHERE email = %s AND password = %s", (email, password))
        user = cur.fetchone()
        
        cur.close()
        conn.close()

        if user:
            # 로그인 성공! 세션에 정보 저장
            session['user_id'] = user[0]
            session['name'] = user[1]
            return redirect(url_for('dashboard')) # 대시보드로 이동
        else:
            flash('이메일 또는 비밀번호가 틀렸습니다.')
            return redirect(url_for('login'))

    return render_template('login.html')

# 3. 로그인 성공 후 이동할 화면 (대시보드)
# app.py의 dashboard 함수 교체

# =========================================================
# 색상 팔레트 (매장별 고정 색상을 위해 사용)
STORE_COLORS = [
    '#FFCDD2', # 빨강 (파스텔)
    "#BBD7EE", # 파랑 (파스텔)
    '#C8E6C9', # 초록 (파스텔)
    '#E1BEE7', # 보라 (파스텔)
    '#FFE0B2', # 주황 (파스텔)
    '#B2DFDB', # 청록 (파스텔)
    '#F0F4C3', # 라임 (파스텔)
]

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    # 1. 파라미터 받기 (년/월/선택된 매장ID)
    year = request.args.get('year', 2025, type=int)
    month = request.args.get('month', 12, type=int)
    current_store_id = request.args.get('store_id', type=int) # 없으면 None (전체보기)

    # 2. 날짜 계산 (이전/다음 달)
    if month == 1: prev_month=12; prev_year=year-1
    else: prev_month=month-1; prev_year=year
    if month == 12: next_month=1; next_year=year+1
    else: next_month=month+1; next_year=year

    conn = get_db_connection()
    cur = conn.cursor()

    # 3. [필터링용] 내가 일하는 매장 목록 가져오기 (드롭다운 메뉴용)
    cur.execute("""
        SELECT s.store_id, s.name 
        FROM StoreUser su
        JOIN Store s ON su.store_id = s.store_id
        WHERE su.user_id = %s
    """, (user_id,))
    my_stores = cur.fetchall() 

    # ★ [추가된 로직] 현재 선택된 매장 이름(current_store_name) 구하기
    current_store_name = "전체 매장" # 기본값
    if current_store_id:
        for store in my_stores:
            if store[0] == current_store_id:
                current_store_name = store[1]
                break

    # 4. SQL 기본 조건 (필터링 적용)
    # 매장이 선택되었으면 SQL 뒤에 붙일 조건문 생성
    filter_condition = ""
    params = [user_id, year, month]
    
    if current_store_id:
        filter_condition = " AND s.store_id = %s "
        params.append(current_store_id)

    # -------------------------------------------------------
    # [Query 1] 내 스케줄 (확정된 것 + 내가 수락해서 대기중인 것 포함)
    # 기존 로직을 합쳐서 가져옵니다.
    # -------------------------------------------------------
    sql_schedule = f"""
        SELECT 
            s.schedule_id, st.store_id, st.name, s.start_time, s.end_time,
            d.deta_id, d.status, d.accepter_id,
            su.hourly_wage,
            s.work_time
        FROM Schedule s
        JOIN Store st ON s.store_id = st.store_id
        JOIN StoreUser su ON s.store_id = su.store_id AND s.user_id = su.user_id
        LEFT JOIN Deta d ON s.schedule_id = d.schedule_id
        WHERE s.user_id = %s 
          AND EXTRACT(YEAR FROM s.start_time) = %s 
          AND EXTRACT(MONTH FROM s.start_time) = %s
          {filter_condition}
        ORDER BY s.start_time ASC
    """
    cur.execute(sql_schedule, tuple(params))
    my_rows = cur.fetchall()

    # -------------------------------------------------------
    # [Query 2] 내가 수락한(승인대기) 남의 스케줄
    # (이건 내 스케줄 테이블엔 없지만 달력엔 보여야 함)
    # -------------------------------------------------------
    # 파라미터 다시 세팅 (user_id, year, month) + optional store_id
    params_pending = [user_id, year, month]
    if current_store_id: params_pending.append(current_store_id)

    sql_pending = f"""
        SELECT d.deta_id, st.store_id, st.name, s.start_time, s.end_time
        FROM Deta d
        JOIN Schedule s ON d.schedule_id = s.schedule_id
        JOIN Store st ON s.store_id = st.store_id
        WHERE d.accepter_id = %s 
          AND d.status = '승인대기'
          AND EXTRACT(YEAR FROM s.start_time) = %s 
          AND EXTRACT(MONTH FROM s.start_time) = %s
          {filter_condition}
    """
    cur.execute(sql_pending, tuple(params_pending))
    pending_rows = cur.fetchall()

    # -------------------------------------------------------
    # [Query 3] 하단 리스트 (전체 대타 내역)
    # 조건: '구하는중'만 보는 게 아니라 전체 다 봄.
    # 단, '완료'된 건 너무 많으면 지저분하니까 최근 것만 보거나 해야겠지만, 일단 다 보여줌.
    # -------------------------------------------------------
    # 파라미터: user_id(내 매장만 보기 위해), + optional store_id
    params_list = [user_id]
    if current_store_id: 
        params_list.append(current_store_id)
        # 쿼리 중간에 넣을 필터 조건
        filter_clause = "AND s.store_id = %s" 
    else:
        filter_clause = ""

    sql_list = f"""
            SELECT 
                d.deta_id, s.schedule_id, st.store_id, st.name, 
                u_req.name, u_acc.name, s.start_time, s.end_time, d.status, d.requester_id,
                su_me.role  -- <--- ★ [추가됨] 이 매장에서의 나의 직급 (인덱스 10번)
            FROM Deta d
            JOIN Schedule s ON d.schedule_id = s.schedule_id
            JOIN Store st ON s.store_id = st.store_id
            JOIN "User" u_req ON d.requester_id = u_req.user_id
            LEFT JOIN "User" u_acc ON d.accepter_id = u_acc.user_id
            -- ★ [추가됨] 이 글을 보는 '나(Session user)'의 정보를 해당 매장에서 찾기
            JOIN StoreUser su_me ON s.store_id = su_me.store_id AND su_me.user_id = %s
            WHERE 1=1
            {filter_clause}
            ORDER BY 
                CASE WHEN d.status = '구하는중' THEN 1 WHEN d.status = '승인대기' THEN 2 ELSE 3 END,
                s.start_time ASC
        """
    # ★ 파라미터 순서 재정의 (쿼리가 바뀌었으므로)
    final_params = [user_id] 
    if current_store_id: final_params.append(current_store_id)
    
    cur.execute(sql_list, tuple(final_params))
    all_requests = cur.fetchall()
    cur.close()
    conn.close()

    # -------------------------------------------------------
    # 데이터 가공 (Calendar Map 만들기)
    # -------------------------------------------------------
    schedule_map = {}
    total_salary = 0

    # 1. 내 스케줄 처리
    for row in my_rows:
        day = row[3].day
        # 색상 결정: store_id를 인덱스로 사용
        color_idx = row[1] % len(STORE_COLORS)
        bg_color = STORE_COLORS[color_idx]

        # ★ [급여 계산 로직]

        hourly_wage = row[8] if row[8] else 0 # 시급이 없으면 0원 처리
        work_interval = row[9]
        
        daily_wage = 0
        if work_interval:
            # timedelta에서 '총 시간(hour)' 추출하기
            total_hours = work_interval.total_seconds() / 3600
            daily_wage = int(total_hours * hourly_wage)
        
        # 총 급여에 누적
        total_salary += daily_wage

        info = {
            'type': 'confirmed',
            'id': row[0], 
            'store_name': row[2],
            'time_str': f"{row[3].strftime('%H:%M')}~{row[4].strftime('%H:%M')}",
            'status': row[6] if row[6] else '없음',
            'bg_color': bg_color,
            'daily_wage': daily_wage,
            'wage_formatted': f"{daily_wage:,}"
        }
        if day in schedule_map: schedule_map[day].append(info)
        else: schedule_map[day] = [info]

    # 2. 승인 대기 스케줄 처리 (흐릿하게)
    for row in pending_rows:
        day = row[3].day
        # 승인 대기는 색상을 좀 다르게 하거나 흐릿하게 처리 (HTML에서 opacity 조절)
        color_idx = row[1] % len(STORE_COLORS)
        bg_color = STORE_COLORS[color_idx] # 같은 매장 색상 쓰되 흐리게

        info = {
            'type': 'pending',
            'deta_id': row[0],
            'store_name': row[2],
            'time_str': f"{row[3].strftime('%H:%M')}~{row[4].strftime('%H:%M')}",
            'status': '승인대기',
            'bg_color': bg_color
        }
        if day in schedule_map: schedule_map[day].append(info)
        else: schedule_map[day] = [info]

    cal = calendar.monthcalendar(year, month)

    total_salary_str = f"{total_salary:,}"

    return render_template('dashboard.html', 
                           name=session['name'], user_id=user_id,
                           year=year, month=month, 
                           calendar_matrix=cal, schedule_map=schedule_map,
                           all_requests=all_requests, # 전체 리스트 전달
                           my_stores=my_stores, current_store_id=current_store_id, # 필터용 데이터
                           current_store_name=current_store_name,
                           total_salary=total_salary_str,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)

# app.py 의 request_deta 함수를 이걸로 교체하고, 그 밑에 cancel_deta를 추가하세요.

# 1. 대타 요청 함수 (수정됨: 상태를 '대기중' -> '구하는중'으로 변경)
@app.route('/request_deta/<int:schedule_id>', methods=['POST'])
def request_deta(schedule_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 상태를 '구하는중'으로 명시해서 저장
        cur.execute("""
            INSERT INTO Deta (schedule_id, requester_id, status)
            VALUES (%s, %s, '구하는중')
        """, (schedule_id, user_id))
        conn.commit()
        flash('대타 요청을 등록했습니다.')
    except Exception as e:
        conn.rollback()
        flash('오류가 발생했습니다.')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('dashboard'))

# 2. ★ 대타 요청 취소 함수
@app.route('/cancel_deta/<int:schedule_id>', methods=['POST'])
def cancel_deta(schedule_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 내가 요청한 대타이고, 아직 '구하는중' 상태일 때만 삭제 가능 (승인대기 상태면 취소 불가하게)
        cur.execute("""
            DELETE FROM Deta 
            WHERE schedule_id = %s AND requester_id = %s AND status = '구하는중'
        """, (schedule_id, user_id))
        
        if cur.rowcount > 0:
            conn.commit()
            flash('대타 요청을 취소했습니다.')
        else:
            flash('취소할 수 없는 상태이거나 권한이 없습니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# 2. ★ 대타 수락 처리 함수 (새로 추가!)
@app.route('/accept_deta/<int:deta_id>/<int:schedule_id>', methods=['POST'])
def accept_deta(deta_id, schedule_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. 스케줄 시간 조회
        cur.execute("SELECT start_time, end_time FROM Schedule WHERE schedule_id = %s", (schedule_id,))
        target_schedule = cur.fetchone()
        target_start = target_schedule[0]
        target_end = target_schedule[1]
        
        # 2. ★ 시간 겹침 확인 (Transaction 조건)
        # 내 스케줄 중에서, 타겟 스케줄과 시간이 겹치는게 있는지 카운트
        check_sql = """
            SELECT COUNT(*) FROM Schedule 
            WHERE user_id = %s 
              AND (
                  (start_time < %s AND end_time > %s) -- 시간이 겹치는 조건
              )
        """
        cur.execute(check_sql, (user_id, target_end, target_start))
        conflict_count = cur.fetchone()[0]
        
        if conflict_count > 0:
            flash('❌ 오류: 해당 시간에 이미 본인의 근무가 있어 수락할 수 없습니다!')
        else:
            # 3. 겹치는 게 없으면 수락 처리 (Update)
            cur.execute("""
                UPDATE Deta 
                SET accepter_id = %s, status = '승인대기' 
                WHERE deta_id = %s AND status = '구하는중'
            """, (user_id, deta_id))
            
            conn.commit()
            flash('✅ 대타 수락 완료! 매니저의 승인을 기다립니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# 2. ★ 수락 취소 함수 (새로 추가)
@app.route('/cancel_accept/<int:deta_id>', methods=['POST'])
def cancel_accept(deta_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 내 이름(accepter_id)을 지우고, 상태를 다시 '구하는중'으로 되돌림 (시장에 다시 내놓기)
        cur.execute("""
            UPDATE Deta 
            SET accepter_id = NULL, status = '구하는중' 
            WHERE deta_id = %s AND accepter_id = %s AND status = '승인대기'
        """, (deta_id, user_id))
        
        if cur.rowcount > 0:
            conn.commit()
            flash('수락을 취소했습니다.')
        else:
            flash('취소할 수 없는 상태입니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# app.py 맨 아래에 추가

@app.route('/approve_deta/<int:deta_id>/<int:schedule_id>', methods=['POST'])
def approve_deta(deta_id, schedule_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # [Transaction 시작]
        # 1. Deta 상태를 '완료'로 변경
        cur.execute("""
            UPDATE Deta 
            SET status = '완료' 
            WHERE deta_id = %s AND status = '승인대기'
        """, (deta_id,))
        
        # 2. Schedule의 주인을 수락자(accepter_id)로 변경
        # (Deta 테이블에 있는 accepter_id를 가져와서 Schedule을 업데이트하는 고급 쿼리)
        cur.execute("""
            UPDATE Schedule
            SET user_id = (SELECT accepter_id FROM Deta WHERE deta_id = %s)
            WHERE schedule_id = %s
        """, (deta_id, schedule_id))
        
        # 두 쿼리가 모두 문제없이 실행되면 저장!
        conn.commit()
        flash('✅ 승인 완료! 스케줄이 변경되었습니다.')
        
    except Exception as e:
        # 하나라도 에러나면 없던 일로 되돌리기
        conn.rollback()
        flash('❌ 오류 발생: ' + str(e))
        
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)