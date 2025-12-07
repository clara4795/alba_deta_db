from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import calendar            
import config
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = config.secret_key

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


# [0]. 메인 페이지 (로그인 화면)
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT user_id, name, email FROM \"User\" WHERE email = %s AND password = %s", (email, password))
        user = cur.fetchone()
        
        cur.close()
        conn.close()

        if user:
            session['user_id'] = user[0]
            session['name'] = user[1]
            return redirect(url_for('main')) # 로그인 후 이동할 곳
        else:
            flash('이메일 또는 비밀번호가 틀렸습니다.')
            return redirect(url_for('login'))

    return render_template('login.html')


# [0-1] 회원가입
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO "User" (name, email, password)
                VALUES (%s, %s, %s)
            """, (name, email, password))
            
            conn.commit()
            flash('가입이 완료되었습니다! 로그인 해주세요.')
            return redirect(url_for('login')) # 성공하면 로그인 페이지로 이동
            
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('❌ 이미 사용 중인 이메일입니다. 다른 이메일을 사용해주세요.')
        except Exception as e:
            conn.rollback()
            flash(f'오류 발생: {e}')
        finally:
            cur.close()
            conn.close()
            
    return render_template('signup.html')


# [1] 메인 페이지
@app.route('/main')
def main():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('main.html', active_page='main')

# 로그아웃
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# [1-1] My 일정표 페이지
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

    #  현재 선택된 매장 이름(current_store_name) 구하기
    current_store_name = "전체 매장" # 기본값
    if current_store_id:
        for store in my_stores:
            if store[0] == current_store_id:
                current_store_name = store[1]
                break

    filter_condition = ""
    params = [user_id, year, month]
    
    if current_store_id:
        filter_condition = " AND s.store_id = %s "
        params.append(current_store_id)

    # -------------------------------------------------------
    # [Query 1] 내 스케줄 (확정된 것 + 내가 수락해서 대기중인 것 포함)
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
    # -------------------------------------------------------
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
    # -------------------------------------------------------
    params_list = [user_id]
    if current_store_id: 
        params_list.append(current_store_id)
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
            JOIN StoreUser su_me ON s.store_id = su_me.store_id AND su_me.user_id = %s
            WHERE 1=1
            {filter_clause}
            ORDER BY 
                CASE WHEN d.status = '구하는중' THEN 1 WHEN d.status = '승인대기' THEN 2 ELSE 3 END,
                s.start_time ASC
        """
    final_params = [user_id] 
    if current_store_id: final_params.append(current_store_id)
    
    cur.execute(sql_list, tuple(final_params))
    all_requests = cur.fetchall()

    # -------------------------------------------------------
    # [Query 4] GROUP BY, having을 활용한 급여 통계
    # -------------------------------------------------------

    # 1. 기본 파라미터 (유저, 연, 월)
    salary_params = [user_id, year, month]
    store_condition = ""

    # 2. 매장이 선택되었다면 조건(AND) 추가
    if current_store_id:
        store_condition = " AND s.store_id = %s "
        salary_params.append(current_store_id)

    # 3. 쿼리 조합 (f-string 사용)
    sql_salary = f"""
        SELECT SUM( EXTRACT(EPOCH FROM s.work_time)/3600 * su.hourly_wage )
        FROM Schedule s
        JOIN StoreUser su ON s.store_id = su.store_id AND s.user_id = su.user_id
        WHERE s.user_id = %s
          AND EXTRACT(YEAR FROM s.start_time) = %s
          AND EXTRACT(MONTH FROM s.start_time) = %s
          {store_condition}
        GROUP BY s.user_id
        HAVING SUM( EXTRACT(EPOCH FROM s.work_time)/3600 * su.hourly_wage ) > 0
    """

    # 4. 실행 (파라미터는 리스트를 튜플로 변환)
    cur.execute(sql_salary, tuple(salary_params))
    salary_result = cur.fetchone()
    
    # 결과 저장
    total_salary = int(salary_result[0]) if salary_result else 0
    cur.close()
    conn.close()

    # -------------------------------------------------------
    # 데이터 가공 (Calendar Map 만들기)
    # -------------------------------------------------------
    schedule_map = {}

    for row in my_rows:  
        day = row[3].day
        color_idx = row[1] % len(STORE_COLORS)
        bg_color = STORE_COLORS[color_idx]
        info = {
                'type': 'confirmed',
                'id': row[0], 
                'store_name': row[2],
                'time_str': f"{row[3].strftime('%H:%M')}~{row[4].strftime('%H:%M')}",
                'status': row[6] if row[6] else '없음',
                'bg_color': bg_color
            }
        if day in schedule_map: schedule_map[day].append(info)
        else: schedule_map[day] = [info]

    # 2. 승인 대기 스케줄 처리 (흐릿하게)
    for row in pending_rows:
        day = row[3].day
        color_idx = row[1] % len(STORE_COLORS)
        bg_color = STORE_COLORS[color_idx] 

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
                           active_page='dashboard',
                           name=session['name'], user_id=user_id,
                           year=year, month=month, 
                           calendar_matrix=cal, schedule_map=schedule_map,
                           all_requests=all_requests, 
                           my_stores=my_stores, current_store_id=current_store_id,
                           current_store_name=current_store_name,
                           total_salary=total_salary_str,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)

# [1-1-1] 대타 요청
@app.route('/request_deta/<int:schedule_id>', methods=['POST'])
def request_deta(schedule_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # [INSERT + Subquery]
        sql = """
            INSERT INTO Deta (schedule_id, requester_id, status)
            SELECT schedule_id, user_id, '구하는중'
            FROM Schedule
            WHERE schedule_id = %s AND user_id = %s
        """
        cur.execute(sql, (schedule_id, user_id))
        
        if cur.rowcount > 0:
            conn.commit()
            flash('대타 요청이 등록되었습니다.')
        else:
            flash('본인의 스케줄만 대타를 요청할 수 있습니다.')
    except Exception as e:
        conn.rollback()
        flash('오류가 발생했습니다.')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('dashboard'))

# [1-1-1] 대타 요청 취소
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
            #flash('대타 요청을 취소했습니다.')
        else:
            flash('취소할 수 없는 상태이거나 권한이 없습니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# [1-1-1] 대타 수락
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
        
        # 2. 시간 겹침 확인 (Transaction 조건)
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

# [1-1-1] 대타 수락 취소
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

# [1-1-1] 대타 승인(매니저, 사장님)
@app.route('/approve_deta/<int:deta_id>/<int:schedule_id>', methods=['POST'])
def approve_deta(deta_id, schedule_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. 스케줄이 속한 매장 ID 조회
        cur.execute("SELECT store_id FROM Schedule WHERE schedule_id = %s", (schedule_id,))
        store_row = cur.fetchone()
        if not store_row: raise Exception("스케줄 정보를 찾을 수 없습니다.")
        store_id = store_row[0]
        
        # 2. 내 권한 확인
        cur.execute("SELECT role FROM StoreUser WHERE store_id = %s AND user_id = %s", (store_id, session['user_id']))
        auth_row = cur.fetchone()
        
        if not auth_row or auth_row[0] not in ['사장님', '매니저']:
             raise Exception("승인 권한이 없습니다.")
        
        cur.execute("""
            UPDATE Deta 
            SET status = '완료' 
            WHERE deta_id = %s AND status = '승인대기'
        """, (deta_id,))
        
        # 2. Schedule의 주인을 수락자(accepter_id)로 변경
        cur.execute("""
            UPDATE Schedule
            SET user_id = (SELECT accepter_id FROM Deta WHERE deta_id = %s)
            WHERE schedule_id = %s
        """, (deta_id, schedule_id))

        conn.commit()
        flash('✅ 승인 완료! 스케줄이 변경되었습니다.')
        
    except Exception as e:
        conn.rollback()
        flash('❌ 오류 발생: ' + str(e))
        
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# [1-2] 전체 일정표 -> 매장 선택 페이지
@app.route('/store_list')
def store_list():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 내가 가입된 매장 목록 조회 (User -> StoreUser -> Store)
    cur.execute("""
        SELECT s.store_id, s.name, su.role
        FROM StoreUser su
        JOIN Store s ON su.store_id = s.store_id
        WHERE su.user_id = %s
    """, (session['user_id'],))
    
    my_stores = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('store_list.html', 
                           active_page='store_list', 
                           my_stores=my_stores)

# [1-2] 전체 근무일정표 보기
@app.route('/store/<int:store_id>')
def store_view(store_id):

    if 'user_id' not in session: return redirect(url_for('login'))
    
    # 1. 날짜 파라미터 받기 (기본값: 현재 년/월)
    year = request.args.get('year', 2025, type=int)
    month = request.args.get('month', 12, type=int)
    
    # 이전/다음 달 계산 (대시보드와 동일 로직)
    if month == 1: prev_month=12; prev_year=year-1
    else: prev_month=month-1; prev_year=year
    if month == 12: next_month=1; next_year=year+1
    else: next_month=month+1; next_year=year

    conn = get_db_connection()
    cur = conn.cursor()

    # 2. 매장 이름 가져오기 (제목 표시용)
    cur.execute("SELECT name FROM Store WHERE store_id = %s", (store_id,))
    store_info = cur.fetchone()
    if not store_info:
        return "존재하지 않는 매장입니다."
    store_name = store_info[0]

    # [2] 내 역할 확인 (사장님/매니저인지 확인용)
    cur.execute("SELECT role FROM StoreUser WHERE store_id = %s AND user_id = %s", (store_id, session['user_id']))
    my_role_row = cur.fetchone()
    my_role = my_role_row[0] if my_role_row else None

    # [3] 직원 목록 조회
    cur.execute("""
        SELECT u.user_id, u.name 
        FROM StoreUser su
        JOIN "User" u ON su.user_id = u.user_id
        WHERE su.store_id = %s
    """, (store_id,))
    employees = cur.fetchall()

    # 3. 해당 매장의 모든 직원 스케줄 조회
    # view(ScheduleInforView) 사용
    sql = """
            SELECT 
            schedule_id, user_name, start_time, end_time, role, user_id
            FROM ScheduleInfoView
            WHERE store_id = %s
            AND EXTRACT(YEAR FROM start_time) = %s 
            AND EXTRACT(MONTH FROM start_time) = %s
            ORDER BY start_time ASC
        """
    cur.execute(sql, (store_id, year, month))
    rows = cur.fetchall()
    
    cur.close()
    conn.close()

    # 4. 달력 데이터
    schedule_map = {}
    for row in rows:
        day = row[2].day
        info = {
            'schedule_id': row[0], 
            'user_name': row[1],
            'time_str': f"{row[2].strftime('%H:%M')}~{row[3].strftime('%H:%M')}",
            'role': row[4],
            'is_me': (row[5] == session['user_id']) 
        }
        if day in schedule_map: schedule_map[day].append(info)
        else: schedule_map[day] = [info]

    cal = calendar.monthcalendar(year, month)

    return render_template('store_schedule.html', 
                           store_name=store_name, store_id=store_id,
                           year=year, month=month, 
                           calendar_matrix=cal, schedule_map=schedule_map,
                           my_role=my_role, employees=employees,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)

# [1-2-1] 매장별 스케줄 - 직원 관리 (사장님)
@app.route('/manage_staff/<int:store_id>')
def manage_staff(store_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # 검색어 받기 (없으면 빈 문자열)
    keyword = request.args.get('q', '')

    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. 권한 체크 (사장님만 가능)
    cur.execute("SELECT role FROM StoreUser WHERE store_id=%s AND user_id=%s", (store_id, session['user_id']))
    res = cur.fetchone()
    if not res or res[0] != '사장님': 
        flash('사장님만 접근 가능한 메뉴입니다.')
        return redirect(url_for('store_view', store_id=store_id))
    
    my_role = res[0]
    
    # 2. 직원 목록 조회 (검색어 필터 적용)
    sql = """
        SELECT u.name, su.role, su.hourly_wage, su.user_id, u.email
        FROM StoreUser su
        JOIN "User" u ON su.user_id = u.user_id
        WHERE su.store_id = %s
    """
    params = [store_id]
    
    # 검색어가 있으면 조건 추가 (이름 검색)
    if keyword:
        sql += " AND u.name ILIKE %s"
        params.append(f'%{keyword}%')
    
    # 정렬 (사장님 -> 매니저 -> 알바생 순)
    sql += """
        ORDER BY 
            CASE WHEN su.role = '사장님' THEN 1 
                 WHEN su.role = '매니저' THEN 2 
                 ELSE 3 END
    """
    
    cur.execute(sql, tuple(params))
    staff_list = cur.fetchall()
    
    # 매장 이름 조회
    cur.execute("SELECT name FROM Store WHERE store_id = %s", (store_id,))
    store_name = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    return render_template('manage_staff.html', 
                           store_id=store_id, 
                           store_name=store_name, 
                           staff_list=staff_list, 
                           my_role=my_role,
                           keyword=keyword)

# [1-2-1] 직원 정보 수정 (사장님)
@app.route('/update_staff/<int:store_id>/<int:target_user_id>', methods=['POST'])
def update_staff(store_id, target_user_id):
    
    if 'user_id' not in session: return redirect(url_for('login'))
    
    new_role = request.form['role']
    new_wage = request.form['hourly_wage']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM StoreUser WHERE store_id = %s AND user_id = %s", (store_id, session['user_id']))
    auth_row = cur.fetchone()
    
    if not auth_row or auth_row[0] != '사장님':
        cur.close()
        conn.close()
        flash('❌ 권한 오류: 사장님만 직원 정보를 수정할 수 있습니다.')
        return redirect(url_for('manage_staff', store_id=store_id))
    
    try:
        cur.execute("""
            UPDATE StoreUser 
            SET role = %s, hourly_wage = %s
            WHERE store_id = %s AND user_id = %s
        """, (new_role, new_wage, store_id, target_user_id))
        conn.commit()
        flash('✅ 직원 정보가 수정되었습니다.')
    except Exception as e:
        conn.rollback()
        flash('오류: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('manage_staff', store_id=store_id))

# [1-2-1] 스케줄 추가
@app.route('/add_schedule/<int:store_id>', methods=['POST'])
def add_schedule(store_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # 폼에서 데이터 받기
    target_user_id = request.form['user_id']
    date_str = request.form['date']       # YYYY-MM-DD
    start_time_str = request.form['start_time'] # HH:MM
    end_time_str = request.form['end_time']     # HH:MM
    
    # DB에 넣을 timestamp 형태로 변환
    start_dt = f"{date_str} {start_time_str}:00"
    end_dt = f"{date_str} {end_time_str}:00"
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM StoreUser WHERE store_id = %s AND user_id = %s", (store_id, session['user_id']))
    auth_row = cur.fetchone()
    
    # 권한이 없거나(None), 알바생인 경우 거부
    if not auth_row or auth_row[0] not in ['사장님', '매니저']:
        cur.close()
        conn.close()
        flash('❌ 권한 오류: 스케줄 추가 권한이 없습니다.')
        return redirect(request.referrer)
    
    try:
        cur.execute("""
            INSERT INTO Schedule (store_id, user_id, start_time, end_time, work_time)
            VALUES (%s, %s, %s, %s, (%s::timestamp - %s::timestamp))
        """, (store_id, target_user_id, start_dt, end_dt, end_dt, start_dt))
        conn.commit()
        flash('✅ 스케줄이 추가되었습니다.')
    except Exception as e:
        conn.rollback()
        flash('❌ 오류: ' + str(e)) # 종료 시간이 시작 시간보다 빠르면 DB constraint 에러 뜸
    finally:
        cur.close()
        conn.close()
        
    # 원래 보던 달력 페이지로 복귀
    return redirect(request.referrer)

# [1-2-1] 스케줄 삭제
@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])
def delete_schedule(schedule_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT store_id FROM Schedule WHERE schedule_id = %s", (schedule_id,))
        sched_row = cur.fetchone()
        
        if not sched_row:
            raise Exception("존재하지 않는 스케줄입니다.")
            
        store_id = sched_row[0]

        # 2. 요청자가 그 매장의 관리자(사장/매니저)인지 확인
        cur.execute("SELECT role FROM StoreUser WHERE store_id = %s AND user_id = %s", (store_id, session['user_id']))
        auth_row = cur.fetchone()

        if not auth_row or auth_row[0] not in ['사장님', '매니저']:
            raise Exception("스케줄 삭제 권한이 없습니다.")

        # 권한 확인 통과 시 삭제 진행
        cur.execute("DELETE FROM Schedule WHERE schedule_id = %s", (schedule_id,))
        conn.commit()
        flash('🗑️ 스케줄이 삭제되었습니다.')
    except:
        conn.rollback()
        flash(f'오류: {e}')
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer)

# [1-3] 매장 등록 및 가입 페이지
@app.route('/store_search')
def store_search():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    keyword = request.args.get('q', '') # 검색어 받기
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 검색 로직 (이름이나 주소에 키워드가 포함되면 조회)
    if keyword:
        cur.execute("""
            SELECT store_id, name, address 
            FROM Store 
            WHERE name ILIKE %s OR address ILIKE %s
            ORDER BY name ASC
        """, (f'%{keyword}%', f'%{keyword}%'))
    else:
        # 검색어 없으면 전체 조회
        cur.execute("SELECT store_id, name, address FROM Store ORDER BY name ASC")
        
    stores = cur.fetchall()
    
    # 내가 이미 가입한 매장 ID 목록 (버튼 상태 구분용)
    cur.execute("SELECT store_id FROM StoreUser WHERE user_id = %s", (session['user_id'],))
    my_joined_ids = [row[0] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return render_template('store_search.html', 
                           active_page='search',
                           stores=stores, 
                           my_joined_ids=my_joined_ids,
                           keyword=keyword)

# [1-3-1] 새 매장 등록
@app.route('/create_store', methods=['POST'])
def create_store():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    name = request.form['name']
    address = request.form['address']
    password = request.form['password'] 
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. 매장 생성
        cur.execute("""
            INSERT INTO Store (name, address, password) 
            VALUES (%s, %s, %s) RETURNING store_id
        """, (name, address, password))
        new_store_id = cur.fetchone()[0]
        
        # 2. 생성한 사람을 '사장님'으로 등록 (시급 NULL 가능)
        cur.execute("""
            INSERT INTO StoreUser (store_id, user_id, role, hourly_wage)
            VALUES (%s, %s, '사장님', NULL)
        """, (new_store_id, session['user_id']))
        
        conn.commit()
        flash(f'✨ {name} 매장이 성공적으로 등록되었습니다!')
        
    except Exception as e:
        conn.rollback()
        flash('❌ 오류 발생 (매장명이 중복되었을 수 있습니다): ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('store_search'))

# [1-3-2] 매장가입 - 비밀번호
@app.route('/join_store_with_pw/<int:store_id>', methods=['POST'])
def join_store_with_pw(store_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    input_pw = request.form['password']
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. 매장 비밀번호 확인
        cur.execute("SELECT password, name FROM Store WHERE store_id = %s", (store_id,))
        result = cur.fetchone()
        
        if not result:
            flash('존재하지 않는 매장입니다.')
            return redirect(url_for('store_search'))
        store_name = result[1]

        # 2. [INSERT + Subquery]
        sql = """
            INSERT INTO StoreUser (store_id, user_id, role, hourly_wage)
            SELECT store_id, %s, '알바생', 0
            FROM Store
            WHERE store_id = %s AND password = %s
        """
        cur.execute(sql, (session['user_id'], store_id, input_pw))
        
        if cur.rowcount > 0:
            conn.commit()
            flash(f'🎉 {store_name}에 가입되었습니다!')
        else:
            flash('❌ 비밀번호가 틀렸습니다.')
            
    except Exception as e:
        conn.rollback()
        flash('이미 가입된 매장이거나 오류가 발생했습니다: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('store_search'))

if __name__ == '__main__':
    app.run(debug=True)