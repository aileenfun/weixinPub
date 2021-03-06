#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:     weixind.py
# Author:       Liang Cha<ckmx945@gmail.com>
# CreateDate:   2014-05-15

import os
import ctypes
import web
import time
import types
import hashlib
import base64
import urllib2
import memcache
from array import *
import RPi.GPIO as GPIO
from lxml import etree
from weixin import WeiXinClient
from weixin import APIError
from weixin import AccessTokenError


_TOKEN = 'alanliu'
_URLS = (
    '/weixin', 'weixinserver',
)
_HELP=('该公众号主要是测试功能通路,炫技用的。程序运行在我家里的嵌入式机器上，使用python语言.\n\n'
    '家里的嵌入式使用ssh反向链接到租用的外网的云服务器上，可以让微信访问到\n\n'
    '其中监控内的功能都已实现，实况截图是嵌入式读取摄像头的图片，以图片消息的形式发送回来\n\n'
    'cpu温度是读取芯片的实时自身温度\n\n'
    '实时监控可以登录一个小网页来看实时的视频，为了你的流量,帧率很低.有些手机浏览器大概不支持实时监控，iPhone是可以的\n\n'
    '测试功能里的按键也基本都可用\n\n'
    '音乐消息是我老婆谈的钢琴曲 ；）\n\n'
    '位置消息，需要将你的位置发送给我，软件进行解析\n\n'
    '\n\n'  
    '发送的文字消息会扔回给你。发送的语音，图片，视频会保存到我这里。\n\n'
    '有意思的是，我看到发送语音消息的通讯协议里面有个“识别”字段，是不是微信后面会开发这个功能呢？\n\n'
    '\n\n'    
    '看起来python做软件原型开发确实方便，下一步会尝试更多的功能 \n#_#'
       )

def _check_hash(data):
    signature = data.signature
    timestamp = data.timestamp
    nonce = data.nonce
    list = [_TOKEN, timestamp, nonce]
    list.sort()
    sha1 = hashlib.sha1()
    map(sha1.update, list)
    hashcode = sha1.hexdigest()
    if hashcode == signature: return True
    return False


def _check_user(user_id):
    user_list = ['o3Oh3s2FEbPxOpr46jUccBlZhIVo']
    if user_id in user_list:
        return True
    return False


def _punctuation_clear(ostr):
    '''Clear XML or dict using special punctuation'''
    return str(ostr).translate(None, '\'\"<>&')


def _cpu_and_gpu_temp():
    '''Get from pi'''
    import commands
    try:
        fd = open('/sys/class/thermal/thermal_zone0/temp')
        ctemp = fd.read()
        fd.close()
        gtemp = commands.getoutput('/opt/vc/bin/vcgencmd measure_temp').replace('temp=', '').replace('\'C', '')
    except Exception, e:
        return (0, 0)
    return (float(ctemp) / 1000, float(gtemp))



def _json_to_ditc(ostr):
    import json
    try:
        return json.loads(ostr)
    except Exception, e:
        return None


def _get_user_info(wc):
    info_list = []
    wkey = 'wacthers_%s' % wc.app_id
    mc = memcache.Client(['127.0.0.1:8001'], debug=0)
    id_list = mc.get(wkey)
    if id_list is None:
        return info_list
    for open_id in id_list:
        req = wc.user.info.dget(openid=open_id, lang='zh_CN')
        name ='%s' %(req.nickname)
        place = '%s,%s,%s' %(req.country, req.province, req.city)
        sex = '%s' %(u'男') if (req.sex == 1) else u'女'
        info_list.append({'name':name, 'place':place, 'sex':sex})
    return info_list


def _udp_client(addr, data):
    import select
    import socket
    mm = '{"errno":1, "msg":"d2FpdCByZXNwb25zZSB0aW1lb3V0"}'
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c.setblocking(False)
    inputs = [c]
    c.connect(addr)
    c.sendall(data)
    readable, writeable, exceptional = select.select(inputs, [], [], 3)
    try:
        if readable: mm = c.recv(2000)
    except Exception, e:
        mm = '{"errno":1, "msg":"%s"}' %(base64.b64encode(_punctuation_clear(e)))
    finally:
        c.close()
    return mm


def _take_snapshot(addr, port, client):
    libc=ctypes.cdll.LoadLibrary('libc.so.6')
    res_init=libc.__res_init
    res_init()
    url = 'http://127.0.0.1:8001/?action=snapshot'
    req = urllib2.Request(url)
    resp = urllib2.urlopen(req, timeout = 20)
    #fh=open("tempimg.jpg","w")
    #fh.write(resp.read())
    #fh.close
    #files={'image':open('tempimg.jpg','rb')}
    #return client.media.upload.file(type='image', jpeg=open('tempimg.jpg','rb'))
    return client.media.upload.file(type='image', jpeg=resp)

def _reply_voice(filename, client):
    return client.media.upload.file(type='voice', amr=open(filename,'rb'))

def _do_event_subscribe(server, fromUser, toUser, doc):
    return server._reply_text(fromUser, toUser, _HELP)


def _do_event_unsubscribe(server, fromUser, toUser, doc):
    return server._reply_text(fromUser, toUser, u'bye!')


def _do_event_SCAN(server, fromUser, toUser, doc):
    pass


def _do_event_LOCATION(server, fromUser, toUser, doc):
    pass


def _do_event_CLICK(server, fromUser, toUser, doc):
    key = doc.find('EventKey').text
    try:
        return _weixin_click_table[key](server, fromUser, toUser, doc)
    except KeyError, e:
        #print '_do_event_CLICK: %s' %e
        return server._reply_text(fromUser, toUser, u'Unknow click: '+key)


_weixin_event_table = {
    'subscribe'     :   _do_event_subscribe,
    'unsbscribe'    :   _do_event_unsubscribe,
    'SCAN'          :   _do_event_SCAN,
    'LOCATION'      :   _do_event_LOCATION,
    'CLICK'         :   _do_event_CLICK,
}


def _do_click_V2001_LIST(server, fromUser, toUser, doc):
    #reply_msg = ''
    #user_list = []
    #try:
        #user_list = _get_user_info(server.client)
    #except AccessTokenError, e:
        #reply_msg = '_get_user_info error: %s' %(_punctuation_clear(str(e)))
        #server.client.refurbish_access_token()
    #except Exception, e:
        #reply_msg = '_get_user_info error: %s' %(_punctuation_clear(str(e)))
    #if user_list:
        #reply_msg = ['%s|%s|%s' %(user['name'], user['place'], user['sex']) for user in user_list]
        #reply_msg = '\n'.join(reply_msg)
    #if not reply_msg: reply_msg = 'No one subscription'
    return server._reply_text(fromUser, toUser, u'我还没想好这按键用来干什么')


def _do_click_V2001_JOIN(server, fromUser, toUser, doc):
    data = None
    err_msg = 'voice fail error: '
    try:
        data = _reply_voice('voicetest.amr', server.client)
	print(data)
    except Exception, e:
        err_msg += _punctuation_clear(str(e))
	print(err_msg)
        return server._reply_text(fromUser, toUser, err_msg)
    print(data.media_id)
    return server._reply_voice(fromUser, toUser, data.media_id)


def _do_click_V2001_MONITORING(server, fromUser, toUser, doc):
    return server._reply_text(fromUser, toUser, _HELP)


def _do_click_V1001_SOCKET(server, fromUser, toUser, doc):
    GPIO.output(18, GPIO.LOW) if GPIO.input(18) else GPIO.output(18, GPIO.HIGH)
    reply_msg = '打开状态' if GPIO.input(18) else '关闭状态'
    return server._reply_text(fromUser, toUser, reply_msg)


def _do_click_V1001_PICTURES(server, fromUser, toUser, xml):
    data = None
    err_msg = 'snapshot fail error: '
    try:
        data = _take_snapshot('127.0.0.1', 8001, server.client)
    except Exception, e:
        err_msg += _punctuation_clear(str(e))
        return server._reply_text(fromUser, toUser, err_msg)
    return server._reply_image(fromUser, toUser, data.media_id)


def _do_click_V1001_TEMPERATURE(server, fromUser, toUser, doc):
    c, g = _cpu_and_gpu_temp()
    reply_msg = u'CPU : %.02f℃\nGPU : %.02f℃\n' %(c, g)
    return server._reply_text(fromUser, toUser, reply_msg)


def _do_click_V3001_WAKEUP(server, fromUser, toUser, doc):
    #import wol
    #ret = False
    #reply_msg = '广播失败'
    #try:
        #ret = wol.wake_on_lan('00:00:00:00:00:00')
    #except Exception, e:
        #print e
        #pass
    #if ret: reply_msg = '广播成功'
    reply_msg = '需要将你的位置发送给我，软件进行解析'
    return server._reply_text(fromUser, toUser, reply_msg)


def _do_click_V3001_SHUTDOWN(server, fromUser, toUser, doc):
    _do_text_command_pc(server,fromUser,toUser,['curl www.baidu.com'])
    return server._reply_text(fromUser, toUser, u'我还没想好这按键用来干什么\n^_^')


def _do_click_V3001_UNDO(server, fromUser, toUser, doc):
    server.client.refurbish_access_token()
    print(_do_text_command_pc(server,fromUser,toUser,['./ftpupload.sh']))
    return server._reply_text(fromUser, toUser, "token refreshed")
    #return _do_text_command_pc(server, fromUser, toUser, ['shutdown -a'])


_weixin_click_table = {
    'V1001_SOCKET'          :   _do_click_V1001_SOCKET,
    'V1001_PICTURES'        :   _do_click_V1001_PICTURES,
    'V1001_TEMPERATURE'     :   _do_click_V1001_TEMPERATURE,
    'V2001_MONITORING'      :   _do_click_V2001_MONITORING,
    'V2001_LIST'            :   _do_click_V2001_LIST,
    'V2001_JOIN'            :   _do_click_V2001_JOIN,
    'V3001_WAKEUP'          :   _do_click_V3001_WAKEUP,
    'V3001_SHUTDOWN'        :   _do_click_V3001_SHUTDOWN,
    'V3001_UNDO'            :   _do_click_V3001_UNDO,
}


def _do_text_command(server, fromUser, toUser, content):
    temp = content.split(',')
    try:
        return _weixin_text_command_table[temp[0]](server, fromUser, toUser, temp[1:])
    except KeyError, e:
        return server._reply_text(fromUser, toUser, u'Unknow command: '+temp[0])


def _do_text_command_security(server, fromUser, toUser, para):
    try:
        data = '{"name":"digitalWrite","para":{"pin":5,"value":%d}}' %(int(para[0]))
    except Exception, e:
        return server._reply_text(fromUser, toUser, str(e))
    buf = _udp_client(('10.0.0.100', 6666), data)
    data = _json_to_ditc(buf)
    errno = None
    reply_msg = None
    if type(data) is types.StringType:
        return server._reply_text(fromUser, toUser, data)
    errno = data['errno']
    if errno == 0:
        reply_msg = data['msg']
    else:
        reply_msg = buf
    return server._reply_text(fromUser, toUser, reply_msg)


def _do_text_command_pc(server, fromUser, toUser, para):
    if not _check_user(fromUser):
        return server._reply_text(fromUser, toUser, u'Permission denied…')
    if para[0] == 'wol':
        return _do_click_V3001_WAKEUP(server, fromUser, toUser, para)
    print para[0]
    reply_msg=os.system(para[0])
    #buf = _udp_client(('10.0.0.100', 55555), para[0])
    #data = _json_to_ditc(buf)
    #if not data:
        #reply_msg = _punctuation_clear(buf.decode('gbk'))
    #else:
        #errno = data['errno']
        #reply_msg = data['msg']
        #reply_msg = (base64.b64decode(reply_msg)).decode('gbk') if reply_msg \
                #else ('运行失败' if errno else '运行成功')
    return server._reply_text(fromUser, toUser, reply_msg)


def _do_text_command_kick_out(server, fromUser, toUser, para):
    msg = 'List is None.'
    wkey = 'wacthers_%s' % server.client.app_id
    try:
        mc = memcache.Client(['127.0.0.1:11211'], debug=0)
        wlist = mc.get(wkey)
        if wlist != None:
            del wlist[int(para[0])]
            mc.replace(wkey, wlist)
            msg = 'Kick out user index=%s' %para
    except Exception, e:
        msg = '_do_text_kick_out error, %r' % e
    return server._reply_text(fromUser, toUser, msg)


def _do_text_command_help(server, fromUser, toUser, para):
    data = "commands:\n"
    for (k, v) in _weixin_text_command_table.items():
        data += "\t%s\n" %(k)
    return server._reply_text(fromUser, toUser, data)


def _do_text_command_ss(server, fromUser, toUser, para):
    import ssc
    msg = ''
    def _unkonw_def():
        return 'unkonw ss command: %s' %para[0]
    ssdef = getattr(ssc, para[0], _unkonw_def)
    msg = ssdef(*para[1:])
    return server._reply_text(fromUser, toUser, msg)


_weixin_text_command_table = {
    'help'                  :   _do_text_command_help,
    'security'              :   _do_text_command_security,
    'kick'                  :   _do_text_command_kick_out,
    'pc'                    :   _do_text_command_pc,
    'ss'                    :   _do_text_command_ss,
}


class weixinserver:

    def __init__(self):
        self.app_root = os.path.dirname(__file__)
        self.templates_root = os.path.join(self.app_root, 'templates')
        self.render = web.template.render(self.templates_root)
        self.client = WeiXinClient('wx79cc706033516e6a', '5b723bbd89923d755a44ef4e9e32a94b')#appid
        try:
	    print("get access token")
            self.client.request_access_token()
        except Exception, e:
	    print("access token error")
            self.client.set_access_token('ThisIsAFakeToken', 1800, persistence=True)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(18, GPIO.OUT)

    def _recv_text(self, fromUser, toUser, doc):
        content = doc.find('Content').text
        if content[0] == ',':
            return _do_text_command(self, fromUser, toUser, content[1:])
        reply_msg = content
        return self._reply_text(fromUser, toUser, reply_msg)

    def _recv_event(self, fromUser, toUser, doc):
        event = doc.find('Event').text
        try:
            return _weixin_event_table[event](self, fromUser, toUser, doc)
        except KeyError, e:
            return self._reply_text(fromUser, toUser, u'Unknow event:%s' %event)

    def _recv_image(self, fromUser, toUser, doc):
        url = doc.find('PicUrl').text
        mid = doc.find('MediaId').text
        rm = self.client.media.get.file(media_id=mid)
        fname = '/home/pi/downloads/pic/wx_%s.jpg' %(time.strftime("%Y_%m_%dT%H_%M_%S", time.localtime()))
        fd = open(fname, 'wb'); fd.write(rm.read()); fd.close(); rm.close()
        return self._reply_text(fromUser, toUser, u'upload to:%s' %url)

    def _recv_voice(self, fromUser, toUser, doc):
        #import subprocess
        cmd = doc.find('Recognition').text
        mid = doc.find('MediaId').text
        rm = self.client.media.get.file(media_id=mid)
        fname = '/home/pi/downloads/voice/wx_%s.amr' %(time.strftime("%Y_%m_%dT%H_%M_%S", time.localtime()))
        fd = open(fname, 'wb'); fd.write(rm.read()); fd.close(); rm.close()
        #subprocess.call(['omxplayer', '-o', 'local', fname])
        if cmd is None:
            return self._reply_text(fromUser, toUser, u'no Recognition, no command');
        return self._reply_text(fromUser, toUser, u'voice received');

    def _recv_video(self, fromUser, toUser, doc):
        pass

    def _recv_shortvideo(self, fromUser, toUser, doc):
        mid = doc.find('MediaId').text
        rm = self.client.media.get.file(media_id=mid)
        fname = '/home/pi/downloads/video/wx_%s.mp4' %(time.strftime("%Y_%m_%dT%H_%M_%S", time.localtime()))
        fd = open(fname, 'wb'); fd.write(rm.read()); fd.close(); rm.close()
        return self._reply_text(fromUser, toUser, u'shortvideo:%s' %fname);

    def _recv_location(self, fromUser, toUser, doc):
	loc_x=doc.find('Location_X').text
	loc_y=doc.find('Location_Y').text
	loc_scale=doc.find('Scale').text
	loc_label=doc.find('Label').text
	reply_msg=u'you are at x:%s,y:%s,scale:%s,Label:%s.\n开门，查水表！' %(loc_x, loc_y, loc_scale, loc_label)
	print(reply_msg)
	return self._reply_text(fromUser,toUser,reply_msg)

    def _recv_link(self, fromUser, toUser, doc):
        pass

    def _reply_text(self, toUser, fromUser, msg):
        return self.render.reply_text(toUser, fromUser, int(time.time()), msg)

    def _reply_image(self, toUser, fromUser, media_id):
        return self.render.reply_image(toUser, fromUser, int(time.time()), media_id)

    def _reply_voice(self,toUser,fromUser,media_id):
	return self.render.reply_voice(toUser,fromUser,int(time.time()),media_id)

    def _reply_news(self, toUser, fromUser, title, descrip, picUrl, hqUrl):
        return self.render.reply_news(toUser, fromUser, int(time.time()), title, descrip, picUrl, hqUrl)

    def GET(self):
        data = web.input()
        try:
            if _check_hash(data):
                return data.echostr
        except Exception, e:
            #print e
            return None

    def POST(self):
        str_xml = web.data()
        doc = etree.fromstring(str_xml)
        msgType = doc.find('MsgType').text
        fromUser = doc.find('FromUserName').text
        toUser = doc.find('ToUserName').text
        print 'from:%s-->to:%s' %(fromUser, toUser)
        print str_xml
        if msgType == 'text':
            return self._recv_text(fromUser, toUser, doc)
        if msgType == 'event':
            return self._recv_event(fromUser, toUser, doc)
        if msgType == 'image':
            return self._recv_image(fromUser, toUser, doc)
        if msgType == 'voice':
            return self._recv_voice(fromUser, toUser, doc)
        if msgType == 'video':
            return self._recv_video(fromUser, toUser, doc)
        if msgType == 'shortvideo':
            return self._recv_shortvideo(fromUser, toUser, doc)
        if msgType == 'location':
            return self._recv_location(fromUser, toUser, doc)
        if msgType == 'link':
            return self._recv_link(fromUser, toUser, doc)
        else:
            return self._reply_text(fromUser, toUser, u'Unknow msg:' + msgType)


#application = web.application(_URLS, globals()).wsgifunc()
application = web.application(_URLS, globals())

if __name__ == "__main__":
    application.run()
