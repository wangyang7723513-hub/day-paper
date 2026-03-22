import requests
import pandas as pd
import configparser
import schedule
import time
import json
import os
import sys
import re
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader
from html2image import Html2Image
from requests_toolbelt.multipart.encoder import MultipartEncoder

# 处理中文环境
if sys.stdout.encoding != 'UTF-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

def log(msg):
    """带时间戳的详细日志输出"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def safe_div(num, den):
    return num / den if den and den != 0 else 0

def calc_ratio_str(cur, prev):
    if not prev or prev == 0 or prev == "—" or prev == 0.0: return "—"
    res = (cur / prev - 1) * 100
    return f"{res:.2f}%"  # 已根据需求去掉了开头的 + 号

def calc_ratio_raw(cur, prev):
    if not prev or prev == 0: return 0
    return round((cur / prev - 1) * 100, 2)

FIELD_MAP = {
    "flow_date": "effectDate", "date_type": "dateTypeNameTwo",
    "flow_total": "passengerFlowValue", "flow_store": "storeFlowValue", "flow_sales": "factPlazaSalesValue",
    "supermarket": "supermarketPeriodIN", "cinema": "cinemaPeriodIN",
    "car_date": "     ", "car_income": "Unnamed: 5", "car_count": "Unnamed: 6"
}

# --- 飞书发送模块 ---
class FeishuBot:
    def __init__(self, app_id, app_secret, webhook_url):
        self.app_id = app_id
        self.app_secret = app_secret
        self.webhook_url = webhook_url
        self.token = self._get_token()

    def _get_token(self):
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=10)
            token = res.json().get('tenant_access_token')
            if token: log("✅ 飞书身份认证成功 (Token 已获取)")
            else: log("❌ 飞书 Token 获取失败，请检查配置")
            return token
        except Exception as e:
            log(f"❌ 飞书 Token 获取异常: {e}")
            return None

    def send_text(self, content):
        try:
            res = requests.post(self.webhook_url, json={"msg_type": "text", "content": {"text": content}}, timeout=10)
            if res.json().get('code') == 0: log("✅ 飞书消息头发送成功")
            else: log(f"⚠️ 飞书消息头反馈: {res.text}")
        except Exception as e: log(f"❌ 飞书文本推送异常: {e}")

    def send_image(self, image_path):
        if not self.token: return
        try:
            log(f"📤 正在上传图片到飞书服务器: {image_path}...")
            upload_url = "https://open.feishu.cn/open-apis/im/v1/images"
            with open(image_path, 'rb') as f:
                form = MultipartEncoder({'image_type': 'message', 'image': ('report.png', f, 'image/png')})
                headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': form.content_type}
                res = requests.post(upload_url, headers=headers, data=form, timeout=15)
                image_key = res.json().get('data', {}).get('image_key')
            
            if image_key:
                log(f"🔑 图片上传成功, ImageKey: {image_key}")
                payload = {"msg_type": "image", "content": {"image_key": image_key}}
                res_push = requests.post(self.webhook_url, json=payload, timeout=10)
                if res_push.json().get('code') == 0: log("🚀 飞书图片推送完成")
                else: log(f"⚠️ 飞书发送失败反馈: {res_push.text}")
        except Exception as e: log(f"❌ 飞书图片发送失败: {e}")

# --- 报表计算引擎 ---
class ReportEngine:
    def __init__(self, df_f, df_c, target_date, yoy_offset=364):
        self.yoy_offset = yoy_offset
        self.target_date = pd.to_datetime(target_date)
        df_f = df_f.copy()
        df_f['dt'] = pd.to_datetime(df_f[FIELD_MAP["flow_date"]], errors='coerce')
        num_cols = [FIELD_MAP["flow_total"], FIELD_MAP["flow_store"], FIELD_MAP["flow_sales"], FIELD_MAP["supermarket"], FIELD_MAP["cinema"]]
        for col in num_cols: df_f[col] = pd.to_numeric(df_f[col], errors='coerce').fillna(0)
        self.df_f = df_f.dropna(subset=['dt'])
        
        df_c = df_c.copy()
        df_c['dt'] = pd.to_datetime(df_c[FIELD_MAP["car_date"]].astype(str).str.strip(), errors='coerce')
        for col in [FIELD_MAP["car_income"], FIELD_MAP["car_count"]]:
            df_c[col] = pd.to_numeric(df_c[col], errors='coerce').fillna(0)
        self.df_c = df_c.dropna(subset=['dt']).copy()
        
        date_type_map = self.df_f.set_index('dt')[FIELD_MAP["date_type"]].to_dict()
        self.df_c.loc[:, FIELD_MAP["date_type"]] = self.df_c['dt'].map(date_type_map)

    def get_stats(self, start, end, num_key, den_key=None, is_car=False):
        df = self.df_c if is_car else self.df_f
        mask = (df['dt'] >= pd.to_datetime(start)) & (df['dt'] <= pd.to_datetime(end))
        sub = df[mask]
        if sub.empty: return 0, 0
        num_sum_val = sub[num_key].sum()
        if den_key: 
            den_sum_val = sub[den_key].sum()
            return safe_div(num_sum_val, den_sum_val), sub.shape[0]
        return num_sum_val, sub.shape[0]

    def get_val_by_date(self, dt, key, is_car=False):
        df = self.df_c if is_car else self.df_f
        return df[df['dt'] == pd.to_datetime(dt)][key].sum()

    def build_row(self, name, num_key, den_key=None, div=1, is_car=False, format_type="num"):
        d = self.target_date
        p = {
            "n": (d, d), "y": (d-timedelta(1), d-timedelta(1)), "w": (d-timedelta(7), d-timedelta(7)), "a": (d-timedelta(self.yoy_offset), d-timedelta(self.yoy_offset)),
            "mtd": (d.replace(day=1), d), 
            "lm": (d.replace(day=1)-pd.DateOffset(months=1), d.replace(day=1)-pd.DateOffset(months=1)+timedelta(d.day-1)),
            "ly": (d.replace(day=1)-pd.DateOffset(years=1), d-pd.DateOffset(years=1)),
            "ytd": (d.replace(month=1, day=1), d),
            "yly": (d.replace(month=1, day=1)-pd.DateOffset(years=1), d-pd.DateOffset(years=1))
        }
        v = {}
        for k, (s, e) in p.items():
            val, cnt = self.get_stats(s, e, num_key, den_key, is_car)
            v[k] = val / div if not den_key else val
            v[k+"_c"] = cnt
        df_base = self.df_c if is_car else self.df_f
        def get_avg(start, end, dtype):
            mask = (df_base['dt'] >= pd.to_datetime(start)) & (df_base['dt'] <= pd.to_datetime(end)) & (df_base[FIELD_MAP["date_type"]] == dtype)
            sub = df_base[mask]
            if sub.empty: return 0
            if den_key: return safe_div(sub[num_key].sum(), sub[den_key].sum())
            return (sub[num_key].sum() / div) / sub.shape[0]
        v_wknd_26, v_wday_26 = get_avg(p['ytd'][0], p['ytd'][1], "周末/假期"), get_avg(p['ytd'][0], p['ytd'][1], "平日")
        v_wknd_25, v_wday_25 = get_avg(p['yly'][0], p['yly'][1], "周末/假期"), get_avg(p['yly'][0], p['yly'][1], "平日")

        def f(val): 
            if format_type == "ratio": return f"{val:.2f}"
            if format_type == "percent": return f"{val*100:.2f}%"
            if format_type == "int": return f"{int(round(val))}"
            return f"{val:.2f}"

        return {
            "name": name, "v_n": f(v['n']), "v_y": f(v['y']), "v_w": f(v['w']), "v_a": f(v['a']),
            "r_y": calc_ratio_str(v['n'], v['y']), "r_w": calc_ratio_str(v['n'], v['w']), "r_a": calc_ratio_str(v['n'], v['a']),
            "m_v": f(v['mtd']), "m_avg": f(safe_div(v['mtd'], v['mtd_c'])) if format_type in ("num", "int") else f(v['mtd']),
            "m_lm": f(v['lm']), "m_lm_avg": f(safe_div(v['lm'], v['lm_c'])) if format_type in ("num", "int") else f(v['lm']),
            "m_ly": f(v['ly']), "m_ly_avg": f(safe_div(v['ly'], v['ly_c'])) if format_type in ("num", "int") else f(v['ly']),
            "m_ratio": calc_ratio_str(v['mtd'], v['lm']), "m_yoy": calc_ratio_str(v['mtd'], v['ly']),
            "y_avg": f(safe_div(v['ytd'], v['ytd_c'])) if format_type in ("num", "int") else f(v['ytd']),
            "y_v": f(v['ytd']), "y_wknd": f(v_wknd_26), "y_wday": f(v_wday_26),
            "y_ly_avg": f(safe_div(v['yly'], v['yly_c'])) if format_type in ("num", "int") else f(v['yly']),
            "y_ly_v": f(v['yly']), "y_ly_wknd": f(v_wknd_25), "y_ly_wday": f(v_wday_25),
            "y_avg_ratio": calc_ratio_str(safe_div(v['ytd'], v['ytd_c']), safe_div(v['yly'], v['yly_c'])),
            "y_wknd_ratio": calc_ratio_str(v_wknd_26, v_wknd_25), "y_wday_ratio": calc_ratio_str(v_wday_26, v_wday_25),
            "y_yoy": calc_ratio_str(v['ytd'], v['yly'])
        }

# --- 核心任务流 ---
def generate_report():
    log("🚀 [任务启动] 开始生成报表流...")
    try:
        config = configparser.ConfigParser()
        config.read('config.ini', encoding='utf-8')
        raw_date = config.get('REPORT_CONFIG', 'target_date').strip()
        
        if raw_date.lower() == 'yesterday':
            target_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            log(f"📅 动态日期模式: 昨日({target_dt.strftime('%Y-%m-%d')})")
        else:
            target_dt = datetime.strptime(raw_date, "%Y-%m-%d")
            log(f"📅 静态日期模式: {raw_date}")
        
        d_target = target_dt.strftime("%Y-%m-%d")
        yoy_offset = config.getint('REPORT_CONFIG', 'yoy_offset', fallback=364)

        log("🌐 正在请求数据 API...")
        f_res = requests.get(config.get('API_CONFIG', 'flow_api_url'))
        if f_res.status_code == 200: log("✅ 客流数据获取成功")
        c_res = requests.get(config.get('API_CONFIG', 'car_api_url'))
        if c_res.status_code == 200: log("✅ 车流数据获取成功")
        w_res = requests.get(config.get('API_CONFIG', 'weather_api_url'))
        if w_res.status_code == 200: log("✅ 天气数据获取成功")

        # --- 停车场数据融合逻辑 ---
        log("🚗 正在进行停车场历史数据融合...")
        csv_file = 'car_history.csv'
        api_car_df = pd.DataFrame(c_res.json())
        
        temp_api = api_car_df[[FIELD_MAP["car_date"], FIELD_MAP["car_income"], FIELD_MAP["car_count"]]].copy()
        temp_api.columns = ['date', 'income', 'count']
        temp_api['date_dt'] = pd.to_datetime(temp_api['date'].astype(str).str.strip(), errors='coerce')
        temp_api = temp_api.dropna(subset=['date_dt'])
        temp_api['date'] = temp_api['date_dt'].dt.strftime('%Y-%m-%d')
        temp_api = temp_api.drop(columns=['date_dt'])

        if os.path.exists(csv_file):
            csv_df = pd.read_csv(csv_file)
            csv_df['date_dt'] = pd.to_datetime(csv_df['date'].astype(str).str.strip(), errors='coerce')
            csv_df = csv_df.dropna(subset=['date_dt'])
            csv_df['date'] = csv_df['date_dt'].dt.strftime('%Y-%m-%d')
            csv_df = csv_df.drop(columns=['date_dt'])
            
            combined_car = pd.concat([csv_df, temp_api]).drop_duplicates(subset=['date'], keep='last')
            combined_car = combined_car.sort_values('date')
            
            try:
                combined_car.to_csv(csv_file, index=False, encoding='utf-8')
                log(f"💾 本地车流库同步成功，当前记录数: {len(combined_car)}")
            except PermissionError:
                log("⚠️ 无法写入 car_history.csv。请关闭 Excel 窗口后再试。")
            
            final_car_df = combined_car.rename(columns={'date': FIELD_MAP["car_date"], 'income': FIELD_MAP["car_income"], 'count': FIELD_MAP["car_count"]})
        else:
            log("⚠️ 未找到 car_history.csv，正在创建...")
            temp_api.to_csv(csv_file, index=False, encoding='utf-8')
            final_car_df = api_car_df

        # --- 天气对齐 ---
        log("🌤️ 处理天气对齐逻辑...")
        weather_db = {}
        if os.path.exists('weather_history.json'):
            with open('weather_history.json', 'r', encoding='utf-8') as f:
                try: weather_db = json.load(f)
                except: pass
        if w_res.status_code == 200:
            weather_db[datetime.now().strftime("%Y-%m-%d")] = w_res.json()['forecasts'][0]['casts'][0]
            with open('weather_history.json', 'w', encoding='utf-8') as f:
                json.dump(weather_db, f, ensure_ascii=False, indent=4)
        
        w_data = weather_db.get(d_target, w_res.json()['forecasts'][0]['casts'][0])
        w_str = f"日间 {w_data['dayweather']} {w_data['daytemp']}℃ 风力 {w_data['daypower']}级 | 夜间 {w_data['nightweather']} {w_data['nighttemp']}℃ 风力 {w_data['nightpower']}级"
        
        log("🔢 正在进行数据计算与行列构建...")
        engine = ReportEngine(pd.DataFrame(f_res.json()), final_car_df, d_target, yoy_offset)
        def get_title(key, default): return config.get('ROW_TITLES', key, fallback=default)
        table_data = []
        rows_cfg = [
            (get_title('flow_plaza', "广场客流 (万)"), FIELD_MAP["flow_total"], None, 10000, False, "num"),
            (get_title('flow_store', "进店客流 (万)"), FIELD_MAP["flow_store"], None, 10000, False, "num"),
            (get_title('rate_store', "进店率"), FIELD_MAP["flow_store"], FIELD_MAP["flow_total"], 1, False, "ratio"),
            (get_title('sales_plaza', "广场销售 (万)"), FIELD_MAP["flow_sales"], None, 10000, False, "num"),
            (get_title('car_out', "出场车流 (辆)"), FIELD_MAP["car_count"], None, 1, True, "int"),
            (get_title('car_income', "停车场收入 (元)"), FIELD_MAP["car_income"], None, 1, True, "int"),
            (get_title('super_flow', "超市"), FIELD_MAP["supermarket"], None, 1, False, "int"),
            (get_title('cinema_flow', "影城"), FIELD_MAP["cinema"], None, 1, False, "int"),
            (get_title('super_rate', "超市占比"), FIELD_MAP["supermarket"], FIELD_MAP["flow_total"], 1, False, "percent"),
            (get_title('cinema_rate', "影城占比"), FIELD_MAP["cinema"], FIELD_MAP["flow_total"], 1, False, "percent"),
        ]
        for r in rows_cfg: table_data.append(engine.build_row(*r))

        log("🎨 正在渲染 HTML 模版...")
        chart_days = int(config.get('CHART_CONFIG', 'days'))
        chart_x, cf_p, cf_s, cc_i, cc_f, cf_p_yoy, cc_f_yoy = [], [], [], [], [], [], []
        cf_super_yoy, cf_cinema_yoy = [], []
        cf_store_yoy, cf_sales_yoy = [], []
        for i in range(chart_days - 1, -1, -1):
            curr_dt = target_dt - timedelta(days=i)
            prev_dt = curr_dt - timedelta(days=yoy_offset)
            chart_x.append(curr_dt.strftime("%m/%d"))
            v_p = engine.get_val_by_date(curr_dt, FIELD_MAP["flow_total"])
            v_s = engine.get_val_by_date(curr_dt, FIELD_MAP["flow_store"])
            v_ci = engine.get_val_by_date(curr_dt, FIELD_MAP["car_income"], True)
            v_cf = engine.get_val_by_date(curr_dt, FIELD_MAP["car_count"], True)
            o_p = engine.get_val_by_date(prev_dt, FIELD_MAP["flow_total"])
            o_cf = engine.get_val_by_date(prev_dt, FIELD_MAP["car_count"], True)
            
            v_super = engine.get_val_by_date(curr_dt, FIELD_MAP["supermarket"])
            v_cinema = engine.get_val_by_date(curr_dt, FIELD_MAP["cinema"])
            o_super = engine.get_val_by_date(prev_dt, FIELD_MAP["supermarket"])
            o_cinema = engine.get_val_by_date(prev_dt, FIELD_MAP["cinema"])
            
            v_sales = engine.get_val_by_date(curr_dt, FIELD_MAP["flow_sales"])
            o_s = engine.get_val_by_date(prev_dt, FIELD_MAP["flow_store"])
            o_sales = engine.get_val_by_date(prev_dt, FIELD_MAP["flow_sales"])
            
            cf_p.append(float(v_p/10000))
            cf_s.append(float(v_s/10000))
            cc_i.append(float(v_ci))
            cc_f.append(int(v_cf))
            cf_p_yoy.append(float(calc_ratio_raw(v_p, o_p)))
            cc_f_yoy.append(float(calc_ratio_raw(v_cf, o_cf)))
            cf_super_yoy.append(float(calc_ratio_raw(v_super, o_super)))
            cf_cinema_yoy.append(float(calc_ratio_raw(v_cinema, o_cinema)))
            cf_store_yoy.append(float(calc_ratio_raw(v_s, o_s)))
            cf_sales_yoy.append(float(calc_ratio_raw(v_sales, o_sales)))

        # 计算 1-12 月均对比
        monthly_plaza_26, monthly_plaza_25 = [], []
        monthly_car_26, monthly_car_25 = [], []
        monthly_store_26, monthly_store_25 = [], []
        monthly_sales_26, monthly_sales_25 = [], []
        cur_year = target_dt.year
        prev_year = cur_year - 1
        for m in range(1, 13):
            # 2025
            start_25 = pd.to_datetime(f"{prev_year}-{m:02d}-01")
            end_25 = start_25 + pd.offsets.MonthEnd(0)
            val_p_25, cnt_p_25 = engine.get_stats(start_25, end_25, FIELD_MAP["flow_total"])
            val_c_25, cnt_c_25 = engine.get_stats(start_25, end_25, FIELD_MAP["car_count"], is_car=True)
            val_s_25, cnt_s_25 = engine.get_stats(start_25, end_25, FIELD_MAP["flow_store"])
            val_sales_25, cnt_sales_25 = engine.get_stats(start_25, end_25, FIELD_MAP["flow_sales"])
            
            monthly_plaza_25.append(float(val_p_25 / cnt_p_25 / 10000) if cnt_p_25 else None)
            monthly_car_25.append(float(val_c_25 / cnt_c_25) if cnt_c_25 else None)
            monthly_store_25.append(float(val_s_25 / cnt_s_25 / 10000) if cnt_s_25 else None)
            monthly_sales_25.append(float(val_sales_25 / cnt_sales_25 / 10000) if cnt_sales_25 else None)
            
            # 2026/Current
            if m > target_dt.month:
                monthly_plaza_26.append(None)
                monthly_car_26.append(None)
                monthly_store_26.append(None)
                monthly_sales_26.append(None)
            else:
                start_26 = pd.to_datetime(f"{cur_year}-{m:02d}-01")
                # 如果是当前月份，算到 target_dt，或者算完整月也行因为未来的cnt本身为0不会计算
                end_26 = start_26 + pd.offsets.MonthEnd(0)
                val_p_26, cnt_p_26 = engine.get_stats(start_26, end_26, FIELD_MAP["flow_total"])
                val_c_26, cnt_c_26 = engine.get_stats(start_26, end_26, FIELD_MAP["car_count"], is_car=True)
                val_s_26, cnt_s_26 = engine.get_stats(start_26, end_26, FIELD_MAP["flow_store"])
                val_sales_26, cnt_sales_26 = engine.get_stats(start_26, end_26, FIELD_MAP["flow_sales"])
                
                monthly_plaza_26.append(float(val_p_26 / cnt_p_26 / 10000) if cnt_p_26 else None)
                monthly_car_26.append(float(val_c_26 / cnt_c_26) if cnt_c_26 else None)
                monthly_store_26.append(float(val_s_26 / cnt_s_26 / 10000) if cnt_s_26 else None)
                monthly_sales_26.append(float(val_sales_26 / cnt_sales_26 / 10000) if cnt_sales_26 else None)

        env = Environment(loader=FileSystemLoader('.'), extensions=['jinja2.ext.do'])
        with open('dynamic_template.html', 'r', encoding='utf-8') as tf: raw_tmpl = tf.read()
        template = env.from_string(raw_tmpl)
        v_styles = dict(config.items('VISUAL_STYLE'))
        v_styles['chart_height'] = config.get('CHART_CONFIG', 'box_height')
        v_styles['font_family'] = config.get('REPORT_CONFIG', 'font_family')
        weekday_str = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][target_dt.weekday()]
        dt_y, dt_w, dt_a = target_dt - timedelta(1), target_dt - timedelta(7), target_dt - timedelta(yoy_offset)
        dates = {"date_n": f"{target_dt.month}月{target_dt.day}日", "date_y": f"{dt_y.month}月{dt_y.day}日", "date_w": f"{dt_w.month}月{dt_w.day}日", "date_a": f"{dt_a.month}月{dt_a.day}日"}

        html_out = template.render(
            col_titles=dict(config.items('COL_TITLES')), report_title=config.get('REPORT_CONFIG', 'title_prefix'),
            report_weekday=weekday_str, weather_str=w_str, table_data=table_data,
            report_day=target_dt.day, report_month=target_dt.month, last_month_name=f"{target_dt.year}年{target_dt.month-1 if target_dt.month>1 else 12}月",
            chart_x=chart_x, cf_plaza=cf_p, cf_store=cf_s, cc_income=cc_i, cc_flow=cc_f, cf_plaza_yoy=cf_p_yoy, cc_flow_yoy=cc_f_yoy,
            cf_super_yoy=cf_super_yoy, cf_cinema_yoy=cf_cinema_yoy,
            cf_store_yoy=cf_store_yoy, cf_sales_yoy=cf_sales_yoy,
            monthly_plaza_25=monthly_plaza_25, monthly_plaza_26=monthly_plaza_26,
            monthly_car_25=monthly_car_25, monthly_car_26=monthly_car_26,
            monthly_store_25=monthly_store_25, monthly_store_26=monthly_store_26,
            monthly_sales_25=monthly_sales_25, monthly_sales_26=monthly_sales_26,
            report_prev_year=prev_year, report_cur_year=cur_year, print_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
            styles=v_styles, chart_cfg=dict(config.items('CHART_CONFIG')), **dates
        )

        png_name = config.get('OUTPUT_CONFIG', 'png_name')
        with open(config.get('OUTPUT_CONFIG', 'html_name'), "w", encoding="utf-8") as f: f.write(html_out)
        
        log("📸 正在截取报表图片 (请稍等，可能需要 5-10 秒)...")
        Html2Image(output_path='.').screenshot(html_file=config.get('OUTPUT_CONFIG', 'html_name'), save_as=png_name, size=(int(config.get('OUTPUT_CONFIG', 'width')), int(config.get('OUTPUT_CONFIG', 'height'))))
        log(f"✅ 报表图片生成成功: {png_name}")

        if config.getboolean('FEISHU_CONFIG', 'enable_feishu', fallback=False):
            log("🔔 准备飞书推送...")
            bot = FeishuBot(config.get('FEISHU_CONFIG', 'app_id'), config.get('FEISHU_CONFIG', 'app_secret'), config.get('FEISHU_CONFIG', 'webhook_url'))
            bot.send_text(f"📊 {target_dt.year}年{target_dt.month}月{target_dt.day}日 {config.get('REPORT_CONFIG', 'title_prefix')}经营日报已生成。")
            bot.send_image(png_name)
        log("🏁 [本轮任务结束] ----------------------------------\n")
    except Exception as e: log(f"❌ 运行错误: {e}")

# --- 启动逻辑 ---
def main():
    config = configparser.ConfigParser()
    config.read('config.ini', encoding='utf-8')
    print("="*60)
    print(f"📊 {config.get('REPORT_CONFIG', 'title_prefix')} 自动化报表系统启动")
    print("="*60)

    # 1. 启动首跑
    log("⚡ [启动首跑] 正在执行首次报表生成任务...")
    generate_report()

    # 2. 定时模式
    if not config.getboolean('SCHEDULE_CONFIG', 'enable_schedule', fallback=False):
        log("🛑 [单次模式] 首跑完成，程序退出。")
        return

    daily_times = config.get('SCHEDULE_CONFIG', 'daily_times', fallback="").split(',')
    active_tasks = 0
    for t in daily_times:
        t_str = t.strip()
        if t_str:
            schedule.every().day.at(t_str).do(generate_report)
            log(f"📌 [任务挂载] 每日 {t_str}")
            active_tasks += 1
    
    if active_tasks > 0:
        log(f"⏳ 定时模式已启动，共计 {active_tasks} 个执行时间点。")
        log("📫 正在等待时间到达...")
        log(f"⏭️ 下次执行预定时间: {schedule.next_run().strftime('%Y-%m-%d %H:%M:%S')}")
    
    last_next_run = schedule.next_run()
    while True:
        schedule.run_pending()
        cur_next_run = schedule.next_run()
        if cur_next_run != last_next_run:
            log(f"⏭️ 下次执行预定时间: {cur_next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            last_next_run = cur_next_run
        time.sleep(1)

if __name__ == "__main__":
    main()