# Github https://github.com/Hudrolax/aliveer

import serial
import time
from datetime import datetime
from time import sleep
import threading
import queue
import sys
import os
import serial.tools.list_ports
import socket
import telebot
from telebot import apihelper
import requests
from RPi import GPIO
from hudro import *
import smtplib
import random
import configparser
import copy
import subprocess
from network_things_rebooter import NetworkThingsRebooter

config_path = '/home/pi/aliveer/settings.ini'
vars_path = '/home/pi/aliveer/vars.ini'
WatchDogTimer = datetime.now()

def create_config():
	if not os.path.exists(config_path):
		config = configparser.ConfigParser()
		config['main'] = {'SendAlarmToTelegram': True,'SendAlarmToEmail': True}
		config['emails'] = {'email-1': 'hudro795@gmail.com','email-2': 's.kondratyev@leskraft.ru'}
		config['TelegramAdmins'] = {'admin1': 'Nazarov;586035868','admin2': 'Kondratyev;490681790'}
		config['server-1'] = {'name': 'server','ip': '192.168.18.202','port': 8686,'rel_number' : 1,'USBState':0,'Server1c_exist':False,'Server1C_user':'','Server1c_pass':'','Server1C_path':''}
		config['server-2'] = {'name': 'node1','ip': '192.168.18.203','port': 8686,'rel_number' : 2,'USBState':1,'Server1c_exist':True,'Server1C_user':'aliveer','Server1c_pass':'93295841','Server1C_path':'/trade2016donate/hs/aliveer/test'}
		with open(config_path, 'w') as configfile:
			config.write(configfile)

StartTime = datetime.now()
SendAlarmToTelegram = True
SendAlarmToEmail = True
DoNotCheckServer1C = datetime(2017, 3, 5, 12, 30, 10)

emails_for_alarm = [] # e-mails list
telegram_users = [] # telegram users list
servers = [] # servers list
backups = [] # backups list
proxylist = ['217.61.124.6:3128','104.244.77.254:8080','94.23.197.219:3128','68.183.147.115:8080','94.177.255.8:8080','94.23.197.219:3128','51.38.69.83:8080','217.61.124.6:80']

OffOnDCVoltage = True # Выключить, если разряжены аккумуляторы
OffOnTime = True 	# Выключать сервера в нерабочее время, если отключилось питание на входе
OnOnTime = True 	# Включать сервера в рабочее время, если они выключены и если еще много заряда аккумулятора
OnIfPowerOn = True	# Включить сервера, если появилось питание на входе

WatchDogPort = '/dev/ttyACM0' # порт подключения вотчдога
WatchDogSerial = None

GPIO.setmode(GPIO.BCM) # говорим о том, что мы будем обращаться к контактам по номеру канала 
GPIO.setup(17, GPIO.OUT) # Настраиваем GPIO пин 17 на вывод (чтобы мигать светодиодом на крышке)

clear = lambda: os.system('clear') # присваиваем переменной функцию очистки экрана
DirectCommandList = 'rel1_on rel1_off rel2_on rel2_off rel3_on rel3_off rel4_on rel4_off vold6 vold8 vold9 vold10' # Список команд, которые можно отправить непосредственно на Arduino
API_TOKEN = '754688581:AAF-1Q1oCOO2kjCnZIfTk-7YYWLPMb9VGuA'
bot = telebot.TeleBot(API_TOKEN, threaded=False) # Конструктор бота

class TelegramUsersClass():
	def __init__(self,name,ID):
		self.name = name
		self.ID = ID

# Send message with TCP/IP Socket
def SendTCPMessage(adr,message):
	data = ''
	try:
		sock = socket.create_connection((adr[0], adr[1]),10)
		sock.send(bytes(message, encoding='UTF-8'))
		data = ClearStr(sock.recv(1024))
	except:
		data = f'error connection to {adr}'	
	finally:	
		try:
			sock.close()
		except:
			pass	
	return data

def SendToSerial(s_port,s,fromarduino):
		try:
			s_port.write(bytes(s,'utf-8'))
		except:
			print('Write error to port '+comport)

def ReadFromSerial(s_port):
	answer = ''
	try:
		answer = str(s_port.readline())
	except:
		print('Read error from port '+comport)
		return answer	
	answer = ClearStr(answer)
	return answer				

def SendAndWaitAnswer(s_port,SendedCommand,fromarduino):
	k=0
	while k<5:
		SendToSerial(s_port,SendedCommand,fromarduino)
		answer = ReadFromSerial(s_port)
		if answer != '':
			return answer
		k+=1
	return 'error'					

def InicializeWatchdog():
	global WatchDogPort
	global WatchDogSerial
	print('Try connect to WatchDog at port '+WatchDogPort)	
	WatchDogSerial=serial.Serial(WatchDogPort,9600, timeout=1)  #change ACM number as found from ls /dev/tty/ACM*
	WatchDogSerial.flushInput()
	WatchDogSerial.flushOutput()
	WatchDogSerial.baudrate=9600
	WatchDogSerial.timeout=1
	WatchDogSerial.write_timeout=1

class Srv1CClass():
	def __init__(self,exist,user='',password='',serviceline=''):
		self.user = user
		self.password = password
		self.serviceline = serviceline
		self.exist = exist
		self.state = False
		self.SendAlert = False

class BaseBackup():
	def __init__(self,name,IP,port):
		self.name = name
		self.adress = (IP,port)
		self.Expiration = ''
		self.ExpirationBool = False
		self.AlertSended = False
		self.AlertSendedTime = datetime.now()
	def CheckState(self):
		self.Expiration = SendTCPMessage(self.adress,f'get_last_backup_ctimediff {self.name}')
		_ExpirationBool = SendTCPMessage(self.adress,f'backup_expiration_bool {self.name}')
		self.ExpirationBool = False
		if _ExpirationBool == 'True':
			self.ExpirationBool = True	 
		if self.ExpirationBool and (not self.AlertSended or (datetime.now()-self.AlertSendedTime).total_seconds() > 86400) and datetime.now().hour > 7:
			SendToAllTelegram(f'Бекап {self.name} просрочен! Необходимо проверить, почему он не делается.')
			self.AlertSended = True
			self.AlertSendedTime = datetime.now()
		elif not self.ExpirationBool:
			self.AlertSended = False		 

class Computer():
	def __init__(self,name,IP,port,rel_number,USBState,srv1c):
		self.name = name
		self.adress = (IP,port)
		self.rel_number = rel_number
		self.USBState = USBState
		self.stateArray = [1 for i in range(4)]
		self.state = True
		self.PowerState = True
		self.cpu_percent = 0
		self.virtual_memory = 0
		self.uptime = '0'
		self.uptimeinsec = 0
		self.SendMemoryAlert = False
		self.SendStateAlert = False
		self.OffByAdmin = True
		self.OnByAdmin = False
		self.srv1c = srv1c
		self.maintenance = False
		self.maintenance_time = datetime.now()

	def CheckState(self):
		answer = SendTCPMessage(self.adress,'ping')
		self.stateArray.pop(0)
		if answer == 'ping':
			self.stateArray.append(1)
		else:
			self.stateArray.append(0)
		coeff = ArrayMA(self.stateArray)
		# Check prog state
		if coeff >= 0.5:
			self.state = True
			self.OnByAdmin = False
		else:
			self.state = False
		# Check power state
		self.PowerState = Arduino.USBState[self.USBState].state
		# Check app state
		try:
			self.cpu_percent = float(SendTCPMessage(self.adress,'cpu_percent'))
			self.virtual_memory = float(SendTCPMessage(self.adress,'virtual_memory'))
			self.uptime = SendTCPMessage(self.adress,'uptime')
			try:
				UpTArray = self.uptime.replace(',','').split(' ')
				self.uptimeinsec = 86400*int(UpTArray[0]) + 3600*int(UpTArray[2]) + 60*int(UpTArray[4]) + int(UpTArray[6])
			except:
				pass
		except:
			pass
		# Memory alert
		try:
			if self.state and self.virtual_memory > 95 and not self.maintenance and datetime.now().hour < 18 and datetime.now().hour >= 8:
				if not self.SendMemoryAlert:
					SendToAllTelegram(f'На компьютере {self.name} осталось менее {100-self.virtual_memory} % памяти!')
					SendToAllTelegramSticker('CAADAgADWQEAAooSqg496g_ZiR69phYE')
					self.SendMemoryAlert = True	
			elif self.virtual_memory < 80:
				self.SendMemoryAlert = False
		except:
			self.SendMemoryAlert = False
		# state alert
		try:
			if not self.state and self.PowerState and not self.OnByAdmin and not self.maintenance and datetime.now().hour >= 8 and datetime.now().hour < 18:
				#print(f'{self.name} истина ')
				if not self.SendStateAlert:
					SendToAllTelegram(f'На компьютере {self.name} включено питание, но не работает скрипт питона!')
					SendToAllTelegramSticker('CAADAgADkwADMNSdEcGnQGRYJeY0FgQ')
					self.SendStateAlert = True	
			elif self.state:
				#print(f'{self.name} ложь ')
				self.SendStateAlert = False
		except:
			self.SendStateAlert = False
		# state server 1C
		if self.srv1c.exist and self.state and self.uptimeinsec > 120 and (datetime.now() - DoNotCheckServer1C).total_seconds() > 300 and not self.maintenance:
			try:
				answer = ClearStr(requests.get(f'http://{self.srv1c.user}:{self.srv1c.password}@{self.adress[0]}{self.srv1c.serviceline}').content)
				if answer == 'im fine':
					self.srv1c.state = True	
			except:
				self.srv1c.state = False
			if not self.srv1c.state:
				if not self.srv1c.SendAlert:
					SendToAllTelegram(f'На компьютере {self.name} не отвечает сервер 1С!')
					self.srv1c.SendAlert = True
			else:
				self.srv1c.SendAlert = False
		# reset maintenance status
		if self.maintenance and (datetime.now() - self.maintenance_time).total_seconds() > 86400:
			self.maintenance = False
			SendToAllTelegram(f'Снял пометку техобслуживания с компьютера {self.name}, т.к. прошли сутки с ее установки.')

	def SendMessage(self,message):
		return SendTCPMessage(self.adress,message)

	def TurnOff(self,delay = 0):
		message = 'shutdown'
		if delay>0:
			message = message+' '+str(delay)
		return SendTCPMessage(self.adress,message)

	def TurnON(self):
		Arduino.RelDef(self.rel_number,True)
		sleep(40)
		Arduino.RelDef(self.rel_number,False)
		return 'ON command sended'

	def Reboot(self,delay = 0):
		message = 'reboot'
		if delay>0:
			message = message+' '+str(delay)
		return SendTCPMessage(self.adress,message)

	def HardReboot(self):
		Arduino.RelDef(self.rel_number,True)
		sleep(40)
		Arduino.RelDef(self.rel_number,False)
		return 'HardReboot command sended'

	def HardOff(self):
		return Arduino.RelDef(self.rel_number,True)	

def CheckComputersAndBackups():
	global WatchDogTimer
	while True:
		try:
			for srv in servers:
				srv.CheckState()
				sleep(0.25)
			for bckp in backups:
				bckp.CheckState()
				sleep(0.25)
			WatchDogTimer = datetime.now()	
		except:
			pass
		sleep(20)	

def WatchDog_func():
	global WatchDogTimer
	while True:
		print((datetime.now()-WatchDogTimer).total_seconds())
		sleep(10)
		if (datetime.now()-WatchDogTimer).total_seconds() > 300: # restart
			sys.exit()

class Pins():
	def __init__(self,pin):
		self.pin = pin
		self.state = True
				
class CArduino():
	def __init__(self):
		self.port = ''
		self.qc = queue.Queue()
		self.qa = queue.Queue()

		self.DCACCVoltageNow = 20
		self.DCACCVolArray = [21 for i in range(20)]
		self.DCACCVoltage= 21;
		self.DCACCVoltageInPercent = 100
		self.ACStateArray = [1 for i in range(600)]
		self.ACExist = False
		self.ACExistNow = False # pin 6
		self.USBState = [Pins(8), Pins(9), Pins(10)] # pin 8-10

	def ReadDCVoltage(self):
		answer = ''
		while answer.find('Voltage A0 =') == -1 and answer != 'error':
			answer = SendAndWaitAnswer(self.port,'volA0',True)
		voltageA0 = answer.replace('Voltage A0 = ','')
		try:
			voltageA0 = int(voltageA0)
			self.DCACCVoltageNow = round(MapFunc(voltageA0,0,1023,0,2205)/3/100,2)
			self.DCACCVolArray.pop(0)
			self.DCACCVolArray.append(self.DCACCVoltageNow)
			self.DCACCVoltage = round(ArrayMA(self.DCACCVolArray),2)
			percent = round(MapFunc(self.DCACCVoltage,10.8,12.65,0,100),0)
			if percent > 100:
				percent = 100
			elif percent < 0:
				percent = 0	
			self.DCACCVoltageInPercent = percent
		except:
			print('error line 172')
			return 'Error convert str to float: '+str(voltageA0)

	def ReadACStatus(self):
		answer = ''
		while answer.find('D6 =') == -1 and answer != 'error':
			answer = SendAndWaitAnswer(self.port,'volD6',True)
		stateD6 = answer.replace('D6 = ','')
		if stateD6 == '1':
			self.ACExistNow = True
			self.ACStateArray.pop(0)
			self.ACStateArray.append(1)
		else:
			self.ACExistNow = False
			self.ACStateArray.pop(0)
			self.ACStateArray.append(0)
		coeff = ArrayMA(self.ACStateArray)
		if coeff == 1:
			self.ACExist = True
		elif coeff == 0:
			self.ACExist = False

	def ReadPinsStatus(self):
		for el in self.USBState: 
			answer = ''
			while answer.find('D%s =' % el.pin) == -1 and answer != 'error':
				answer = SendAndWaitAnswer(self.port,'volD%s' % el.pin,True)
			state = answer.replace('D%s = ' % el.pin,'')
			if state == '1':
				el.state = True
			else:
				el.state = False

	def Initialize(self):
		isFind = False
		while not isFind: 
			ports = list(serial.tools.list_ports.comports())
			for p in ports:
				comport = p.device
				print('Try to find Arduino in '+comport)
				self.port=serial.Serial(comport,9600, timeout=1)  #change ACM number as found from ls /dev/tty/ACM*
				self.port.flushInput()
				self.port.flushOutput()
				self.port.baudrate=9600
				self.port.timeout=1
				self.port.write_timeout=1
				k=0
				while k<10:
					SendToSerial(self.port,'initialize',True)
					#time.sleep(0.2)
					answer = str(self.port.readline())
					answer = answer.replace("\\r\\n",'')
					answer = answer.replace("b'",'')
					answer = answer.replace("'",'')
					print('.', end='', flush=True)
					if answer == 'initialized':
						isFind = True
						break
					k+=1
				if isFind: # Stop find if arduino is finded
					break
			if not isFind:
				print('I have not found the Arduino...')
				print("Sorry, but i can't work whithout Arduino subcontroller :(")
				print("I'm have to try to find it after 10 second pause")
				sleep(10)
			else:
				print('Arduino is initialized on port '+comport)

	def Reinitializing(self):
		print("I'am lost connection to the Arduino. Now i to try reinitialize subcontroller!")
		self.Initialize()

	def RelDef(self,rel,state):
		if state:
			str_state = 'ON'
			command = 'on'
		else:
			str_state = 'OFF'
			command = 'off'
		answer = self.ExecuteCommand("rel%r_%s" % (rel, command))
		return answer

	def ExecuteCommand(self,_command):
		n1 = 0
		while n1<100:
			if self.qc.qsize() == 0: # Ждем, пока очередь освободится
				self.qc.put(_command) # Помещаем команду в очередь на исполнение
				n2 = 0
				while n2<100: 
					if self.qa.qsize() > 0: # Ждем, пока не придет ответ
						return self.qa.get()
					n2 += 1
					sleep(0.1)
			n1 += 1
			sleep(0.1)
		return 'Error put command in queue'

	def IOQueue(self):
		while True:
			if self.qc.qsize() > 0:
				c = self.qc.get()
				answer = SendAndWaitAnswer(self.port,c,True)
				self.qa.put(answer)
			self.ReadDCVoltage()
			self.ReadACStatus()
			self.ReadPinsStatus()
			sleep(0.1)

Arduino = CArduino() # конструктор Arduino

class AlertsClass():
	def __init__(self,mailServer,user,password):
		self.MailServer = mailServer
		self.user = user
		self.password = password
		self.AlertDCVoltageToTelegramSended = False
		self.AlertDCVoltageToEmailSended = False
		self.AlertACLossToTelegrammSended = False
		self.AlertACLossToEmailSended = False
		self.AlertOffServersByDCLossTelegramm = False
		self.AlertOffServersByDCLossEmail = False
		self.AlertOnServersTelegramm = False
		self.AlertOnServersEmail = False

	def SendDCVoltageAlert(self,voltage):
		if not self.AlertDCVoltageToTelegramSended:
			message = 'Напряжение аккумулятора ИБП опустилось ниже %s V, сейчас произойдет отключение серверов.' % voltage
			# Отправка в телегу
			if SendAlarmToTelegram:
				try:
					SendToAllTelegram(message)
					self.AlertDCVoltageToTelegramSended = True
				except:
					pass
			# отправка на мыло
			if SendAlarmToEmail:
				try:
					self.SendEmail(emails_for_alarm,'Аккум на ИБП сдыхает',message)
					self.AlertDCVoltageToEmailSended = True
				except:
					pass

	def SendACStatusAlert(self):
		if not self.AlertACLossToTelegrammSended:
			message = 'Пропало питание на входе ИБП! Напряжение аккумулятора %s V (%s%%)' % (Arduino.DCACCVoltage, Arduino.DCACCVoltageInPercent)
			# Отправка в телегу
			if SendAlarmToTelegram:
				try:
					SendToAllTelegram(message)
					self.AlertACLossToTelegrammSended = True
				except:
					pass
			# отправка на мыло
			if SendAlarmToEmail:
				try:
					self.SendEmail(emails_for_alarm,'Пропало питание!',message)
					self.AlertACLossToEmailSended = True
				except:
					pass

	def SendOffServersAlert(self, delay, reason):
		if not self.AlertOffServersByDCLossTelegramm:
			message = ''
			if reason == 'DC loss':
				message = 'Отключаю серверы через %s секунд, т.к. напряжение батареи ниже %s V' % (delay,Arduino.DCACCVoltage)
			elif reason == 'by AC loss and schedule':
				message = 'Отключаю серверы через %s секунд, т.к. нет питания на входе и не рабочее время' % delay
			# Отправка в телегу
			if SendAlarmToTelegram:
				try:
					SendToAllTelegram(message)
					self.AlertOffServersByDCLossTelegramm = True
				except:
					pass
			# отправка на мыло
			if SendAlarmToEmail:
				try:
					self.SendEmail(emails_for_alarm,'Отключение серверов!',message)
					self.AlertOffServersByDCLossEmail = True
				except:
					pass

	def SendOnServersAlert(self, reason):
		if not self.AlertOnServersTelegramm:
			message = ''
			if reason == 'ON by schedule':
				message = 'Включаю сервера, т.к. уже рабочее время и заряд аккумулятора еще в порядке.'
			elif reason == 'ON by power on':
				message = 'Включаю сервера, т.к. включилось питание на входе.'
			# Отправка в телегу
			if SendAlarmToTelegram:
				try:
					SendToAllTelegram(message)
					self.AlertOnServersTelegramm = True
				except:
					pass
			# отправка на мыло
			if SendAlarmToEmail:
				try:
					self.SendEmail(emails_for_alarm,'Включение серверов!',message)
					self.AlertOnServersEmail = True
				except:
					pass

	def SendEmail(self,_to,subject,message):
		SendEmail(self.MailServer,self.user,self.password,_to,subject,message)

	def CheckSelf(self):
		if self.AlertDCVoltageToTelegramSended and Arduino.DCACCVoltage>12:
			self.AlertDCVoltageToTelegramSended = False
		if self.AlertDCVoltageToEmailSended and Arduino.DCACCVoltage>12:
			self.AlertDCVoltageToEmailSended = False
		if self.AlertACLossToTelegrammSended and Arduino.ACExist:
			self.AlertACLossToTelegrammSended = False
		if self.AlertACLossToEmailSended and Arduino.ACExist:
			self.AlertACLossToEmailSended = False
		if self.AlertOffServersByDCLossTelegramm and Arduino.ACExist:
			self.AlertOffServersByDCLossTelegramm = False
		if self.AlertOffServersByDCLossEmail and Arduino.ACExist:
			self.AlertOffServersByDCLossEmail = False
		if self.AlertOnServersTelegramm and Arduino.ACExist:
			self.AlertOnServersTelegramm = False
		if self.AlertOnServersEmail and Arduino.ACExist:
			self.AlertOnServersEmail = False

Alerts = AlertsClass('smtp.gmail.com:465','aliveerbot@gmail.com','wngpzqmufcpidyrk') # Конструктор алертов

# Function of input in thread
def read_kbd_input(inputQueue):
	while True:
		# Receive keyboard input from user.
		try:
			input_str = input()
			print('Enter command: '+input_str)
			inputQueue.put(input_str)
		except:
			continue	

# Command processing module
def CommandProcessing(_command,telegramuser,message):
	_command = _command.lower()
	
	if telegramuser != None:
		telegramusername = telegramuser.name
	else:
		telegramusername = 'Кто-то из консоли'
	if _command == "exit":
		if telegramuser != None:
			SendToTelegramId(telegramuser.ID,'bye...')
			sleep(5)
		else:
			print('bye...')	
		GPIO.cleanup()
		sys.exit()
	elif _command.find('hard reboot ') > -1:
		name = _command.replace('hard reboot ','')
		computer = None
		for srv in servers:
			if srv.name == name:
				computer = srv
		if computer != None:
			if computer.PowerState: 
				computer.OnByAdmin = True
				if telegramuser != None:
					SendToTelegramId(telegramuser.ID,'Отправил команду жесткого ребута на '+name)
				else:
					print('Отправил команду жесткого ребута на '+name)	
				computer.HardReboot()
				SendToAllTelegram(f'{telegramusername} отправил команду жесткого ребута на {name}')
			else:
				if telegramuser != None:
					SendToTelegramId(telegramuser.ID,f'{name} выключен по питанию, куда его еще ребутить?')
				else:
					print(f'{name} выключен по питанию, куда его еще ребутить?')	
			return None
		else:
			return 'Computer named %s is not exist' % name
	elif _command.startswith('hard off ') or _command.startswith('жестко выключи ') or _command.startswith('выключи питание на ') or _command.startswith('отключи питание на '):	
		name = _command.replace('hard off ','')
		name = name.replace('жестко выключи ','')
		name = name.replace('выключи питание на ','')
		name = name.replace('отключи питание на ','')
		computer = None
		for comp in servers:
			if comp.name == name:
				computer = comp
		if computer != None:
			if computer.PowerState:
				computer.OffByAdmin = True
				computer.HardOff()
				if telegramuser != None:
					SendToTelegramId(telegramuser.ID,'Отправил команду жесткого отключения на '+name)
				else:
					print('Отправил команду жесткого отключения на '+name)
				SendToAllTelegram(f'{telegramusername} отправил команду жесткого отключения на {name}')		
			else:
				return f'{name} выключен по питанию, как я тебе его еще сильнее отключу?' 
			return None
		else:
			return 'Computer named %s is not exist (hard off)' % name
	elif _command.startswith('on ') or _command.startswith('turn on ') or _command.startswith('включи питание на ') or _command.startswith('включи '):	
		name = _command.replace('turn on ','')
		name = _command.replace('on ','')
		name = name.replace('включи питание на ','')
		name = name.replace('включи ','')
		computer = None
		for comp in servers:
			if comp.name == name:
				computer = comp
		if computer != None:
			if computer.state or computer.PowerState:
				return f'{name} уже включен, куда сильнее-то включать? Чекай давай пингом или RDP.'
			else:	 
				computer.OffByAdmin = True
				computer.OnByAdmin = True
				if telegramuser != None: 
					SendToTelegramId(telegramuser.ID,'Отправил команду включения на '+name)
				else:
					print('Отправил команду включения на '+name)	
				computer.TurnON()
				SendToAllTelegram(f'{telegramusername} отправил команду включения на {name}')
			return None
		else:
			return 'Computer named %s is not exist (turn on)' % name				
	elif _command.find('reboot')>-1 or _command.find('перезагрузи')>-1:
		arr = _command.split(' ')
		computer = None
		for i in arr:
			for comp in servers:
				if comp.name == i:
					computer = comp
					break
			if computer != None:
				break
		if computer != None:
			if not computer.PowerState:
				return f'На компе {computer.name} не нет питания. Не выйдет его ребутнуть, вообще никак.' 
			if not computer.state:
				return f'На компе {computer.name} не работает скрипт питоне. Не выйдет его ребутнуть командой этой.' 
			delay = 5
			try:
				if len(arr)>2:
					delay=int(arr[2])
				computer.OnByAdmin = True
				computer.Reboot(delay)
				if telegramuser != None:
					bot.reply_to(message,'Отправил команду перезагрузки на '+computer.name)
					sticker = random.choice([None,'CAADAgADawMAAs-71A73Li-J5B9bRhYE','CAADAwADIwIAAr-MkATmsP44Orn8fBYE'])
					if sticker != None:
						SendToTelegramIdSticker(telegramuser.ID,sticker)
					SendToAllTelegram(f'{telegramuser.name} отправил команду перезагрузки на {computer.name}')	
				else:
					print('Отправил команду перезагрузки на '+computer.name)
				return None	
			except:
				return 'error int(arr[1])'
		else:
			return f'Вы отправили команду {_command}, не нашел компьютер с нужным именем.'
	elif _command.find('кончил')==-1 and _command.find('кончить')==-1 and _command.find('снять')==-1 and (_command.find('обслуживани')>-1 or _command.find('ремонт')>-1): # пометка техобслуживания
		arr = _command.split(' ')
		computer = None
		for i in arr:
			for comp in servers:
				if comp.name == i:
					computer = comp
					break
			if computer != None:
				break 
		if computer != None:
			computer.maintenance = True
			computer.maintenance_time = datetime.now()
			if message != None:
				bot.reply_to(message, f'Компьютер {computer.name} помечен на техобслуживание.')
				SendToAllTelegram(f'{telegramuser.name} установил пометку техобслуживания на {computer.name}')
			else:
				print(f'Компьютер {computer.name} помечен на техобслуживание.')	
			return None
		else:
			return f'Computer named {computer.name} is not exist (maintenance)'
	elif (_command.find('завершил')>-1 or _command.find('кончил')>-1 or _command.find('кончить')>-1 or _command.find('снять')>-1) and (_command.find('обслуживани')>-1 or _command.find('ремонт')>-1 or _command.find('метку')>-1): # окончание обслуживания
		arr = _command.split(' ')
		computer = None
		for i in arr:
			for comp in servers:
				if comp.name == i:
					computer = comp
					break
			if computer != None:
				break 		
		if computer != None:
			computer.maintenance = False
			if telegramuser != None:
				bot.reply_to(message, f'С компьютера {computer.name} снята пометка техобслуживания.')
				SendToAllTelegram(f'{telegramuser.name} снял пометку техобслуживания с {computer.name}')
			else:
				print(f'С компьютера {computer.name} снята пометка техобслуживания.')	
			return None
		else:
			return f'Computer named {computer.name} is not exist (end maintenance)'				
	elif (_command.startswith('shutdown ') or _command.startswith('выключи ') or _command.startswith('отключи ')) and not (_command == 'shutdown all' or _command == 'выключи все' or _command == 'выключить все' or _command == 'отключи все'):
		command = _command.replace('shutdown ','')
		command = command.replace('выключи ','')
		command = command.replace('отключи ','')
		arr = command.split(' ')
		name = arr[0]
		computer = None
		for comp in servers:
			if comp.name == name:
				computer = comp
		if computer != None:
			if not computer.PowerState:
				return f'На компе {name} нет питания. Не выйдет его выключить еще сильнее, вообще никак.' 
			if not computer.state:
				return f'На компе {name} нет питания. Не выйдет его выключить командой этой.'
			delay = 5
			try:
				if len(arr)>1:
					delay=int(arr[1])
				computer.OffByAdmin = True	
				computer.TurnOff(delay)
				if telegramuser != None:
					SendToTelegramId(telegramuser.ID,'Отправил команду отключения на '+name)
					SendToTelegramIdSticker(telegramuser.ID,'CAADAgAD7gMAAvJ-ggyvHBDkw4sLaBYE')
					SendToAllTelegram(f'{telegramuser.name} отправил команду отключения на {name}')
				else:
					print('Отправил команду отключения на '+name)
				return None	
			except:
				return 'error int(arr[1])'
		else:
			return 'Computer named %s is not exist (shutdown)' % name
	elif _command == 'shutdown all' or _command == 'выключи все' or _command == 'выключить все' or _command == 'отключи все':
		for comp in servers:
			comp.OffByAdmin = True
			comp.TurnOff()	
		if telegramuser != None:
			SendToTelegramId(telegramuser.ID,'Отправил команду завершения работы на все сервера')
			SendToTelegramIdSticker(telegramuser.ID,'CAADAgAD3AADVp29Cpy9Gm5Tg192FgQ')
			SendToAllTelegram(f'{telegramuser.name} отправил команду отключения на все сервера')
		else:
			print('Отправил команду завершения работы на все сервера')
		return None	
	elif _command == 'exterminatus' or _command == 'экстерминатус':
		for comp in servers:
			comp.OffByAdmin = True
			comp.HardOff()	
		if telegramuser != None:
			SendToTelegramId(telegramuser.ID,'Отправил команду жесткого отключения на все сервера')
			SendToTelegramIdSticker(telegramuser.ID,'CAADAgAD3AADVp29Cpy9Gm5Tg192FgQ')
			SendToAllTelegram(f'{telegramuser.name} отправил команду экстерминатус на все сервера. Все, пиздец.')
		else:
			print('Отправил команду жесткого отключения на все сервера')
		return None									
	elif _command == "clear" :
		clear()
	elif DirectCommandList.find(_command)>-1:
		return Arduino.ExecuteCommand(_command)
	elif _command.find('send to ') > -1:
		s = _command.replace('send to ','').split(' ')
		name = s.pop(0)
		message = ' '.join(s)
		computer = None
		for comp in servers:
			if comp.name == name:
				computer = comp
		if computer != None:
			#print("Computer name %s. Message: '%s'" % (name, message))
			answer = computer.SendMessage(message)
			return 'Answer: %s' % answer
		else:
			return 'Computer named %s is not exist (send to)' % name
	elif 'voltage'.find(_command) > -1:
		if telegramuser != None:
			SendToTelegramId(telegramuser.ID,'Current ACC voltage is %s V' % Arduino.DCACCVoltageNow)
			SendToTelegramId(telegramuser.ID,'Approximately ACC voltage is %s V' % Arduino.DCACCVoltage)
		else:
			print('Current ACC voltage is %s V' % Arduino.DCACCVoltageNow)
			print('Approximately ACC voltage is %s V' % Arduino.DCACCVoltage)
		return None
	elif _command.find('state')>-1 or _command.find('status')>-1 or _command.find('статус')>-1 or ((_command.find('что там')>-1 or _command.find('че там')>-1) and _command.find('сервер')>-1):
		answer = ''
		try:
			answer += 'pi uptime: '+DifferenceBetweenDate(StartTime,datetime.now())+'\n'
			answer += 'Статус компьютеров:\n'
			for comp in servers:
				answer += f' {comp.name}:'
				if comp.maintenance:
					answer += ' ТЕХОБСЛУЖИВАНИЕ\n'
				else:	
					answer += '\n'	
					uptime = ''
					if comp.state:
						uptime = ' (uptime %s)' % comp.uptime	 
					answer += '     prog %s' % StrOnOFF(comp.state) + uptime+'\n'
					answer += '     power %s\n' % StrOnOFF(comp.PowerState)
					if comp.srv1c.exist:
						answer += f'     1C {StrOnOFF(comp.srv1c.state)}'+'\n'
					if comp.state:
						answer += '     CPU '+str(comp.cpu_percent)+' % ' + 'Memory '+str(comp.virtual_memory)+' %\n'
			answer += '\n'		

			answer += 'Бекапы:\n'			 
			if len(backups)>0:
				for backup in backups:
					answer += f'    {backup.name}: {backup.Expiration}'
					if backup.ExpirationBool:
						answer += ' АХТУНГ!!!'
					answer += '\n'
			else:		
				answer += '    бекапы не настроены...\n'
			answer += '\n'	

			answer += 'Напряжение аккумулятора %s V (%s %%)' % (Arduino.DCACCVoltage, Arduino.DCACCVoltageInPercent) + '\n'
			input_power = 'НЕТ'
			if Arduino.ACExist:
				input_power = 'Есть'
			input_power_now = 'НЕТ'
			if Arduino.ACExistNow:
				input_power_now = 'Есть'	
			answer += 'Входное питание: %s' % input_power +'\n'
		except:
			pass	
		return answer
	elif _command.find('не дрочи 1с')>-1 or _command.find('не дрочи 1c')>-1 or _command.find('не дрочи сервер 1c')>-1 or _command.find('не дрочи сервер 1с')>-1:
		global DoNotCheckServer1C
		DoNotCheckServer1C = datetime.now()
		return 'слушаюсь'
	elif _command.find('отключи вотчдог служб')>-1 or _command.find('stop_check_services')>-1:
		for comp in servers:
			answ = comp.SendMessage("stop_check_services")	
		return 'отправил команду отключения вотчдога служб. Вотчдог сам включится через 3 часа.'				 		
	else:
		return 'unknown command: '+_command	

# Telegram bot
@bot.message_handler(content_types=['text'])
def get_text_messages(message):
	_user = None
	for user in telegram_users: 
		if str(message.from_user.id) == user.ID:
			_user = user
			break
	if message.text == "Привет":
		bot.reply_to(message, "Привет, чем я могу тебе помочь?")
	elif message.text == "/help" or message.text == "help":
		if _user != None:
			helpmessage = 'Help:\n'
			helpmessage += 'getmyid - получить свой telegram ID\n'
			helpmessage += '\n'
			helpmessage += 'status/state/статус - посмотреть статус устройств\n'
			helpmessage += '\n'
			helpmessage += 'reboot/перезагрузи <name> <delay> - отправить команду перезагрузки на компьютер <name> с задержкой <delay> секунд\n'
			helpmessage += '\n'
			helpmessage += 'hard reboot <name> - перезагрузить компьютер <name> через отключение питания\n'
			helpmessage += '\n'
			helpmessage += 'shutdown/выключи/отключи <name> <delay> - выключить компьютер <name> с задержкой <delay> секунд\n'
			helpmessage += '\n'
			helpmessage += 'hard off/отключи питание на <name> - жестко выключить компьютер <name> по питанию\n'
			helpmessage += '\n'
			helpmessage += 'on/turn on/включи питание на <name> - включить компьютер <name>\n'
			helpmessage += '\n'
			helpmessage += 'shutdown all/выключи все - выключить все компьютеры через завершение работы\n'
			helpmessage += '\n'
			helpmessage += 'exterminatus/экстерминатус - выключить все нахуй\n'
			helpmessage += '\n'
			helpmessage += 'обслуживание <computername> - включить пометку техобслуживания для <computername>\n'
			helpmessage += '\n'
			helpmessage += 'закончил обслуживание <computername> - снять пометку техобслуживания для <computername>\n'
			helpmessage += '\n'
			helpmessage += 'служебные команды:\n'
			helpmessage += 'send to <name> <message> - отправить компьютеру <name> сообщение <message>\n'
			helpmessage += '\n'
			helpmessage += 'relN_on/relN_off - отправить команду ON/OFF на реле N непосредственно\n'
			helpmessage += '\n'
			helpmessage += 'voltage - показать среднее и моментальное напряжение батареи\n'
			helpmessage += '\n'
			helpmessage += 'не дрочи 1с - приостановить подключения к серверу 1С на 5 минут\n'
			helpmessage += '\n'
			helpmessage += 'getconfig - получить файл конфига\n'
			helpmessage += '\n'
			helpmessage += 'отправить файл settings.ini - заменить и перезагрузить конфиг\n'
			helpmessage += '\n'
			helpmessage += 'send to golden1 update_base - запустить батник обновления базы\n'
			helpmessage += '\n'
			helpmessage += 'send to golden1 get_log - запросить лог обновления базы\n'
			helpmessage += '\n'
			helpmessage += 'отключи вотчдог служб - отключить вотчдог служб на 3 часа\n'

			bot.send_message(message.from_user.id, helpmessage)
			sticker = random.choice([None,'CAADAgAD4gMAAsSraAugnZfDFQtF3RYE','CAADAgAD-wEAAsoDBgunb7h3gbhrchYE','CAADAgADhgADnNbnCqwnwNen6VDWFgQ','CAADAgADMwEAAu7EoQp4cwmtNchFiRYE','CAADAgADwQIAAu7EoQrlofeMm-V3MBYE'])
			if sticker != None:
				 bot.send_sticker(message.from_user.id, sticker)
		else:
			bot.reply_to(message, "Кто ты чудовище?")		 
	elif message.text == 'getmyid':
		bot.reply_to(message, "Ваш ID: %s" % message.from_user.id)
	elif message.text == 'getconfig':
		if _user != None:
			doc = open('/home/pi/aliveer/settings.ini', 'rb')
			bot.send_document(message.from_user.id, doc)
		else:
			bot.reply_to(message, "Кто ты чудовище?")	
	else:
		if _user != None:
			answer = CommandProcessing(message.text, _user,message)
			if answer != None:
				bot.reply_to(message, answer)
		else:
			bot.reply_to(message, "Кто ты чудовище?")

@bot.message_handler(content_types=["sticker",'document'])
def handle_docs_audio(message):
	_user = None
	for user in telegram_users: 
		if str(message.from_user.id) == user.ID:
			_user = user
			break
	if _user != None:
		if message.content_type == 'sticker':
			# Получим ID Стикера
			sticker_id = message.sticker.file_id
			bot.send_message(message.from_user.id, str(sticker_id))
		elif message.content_type == 'document':
			if message.document.file_name == '/home/pi/aliveer/settings.ini': 
				file_info = bot.get_file(message.document.file_id)
				downloaded_file = bot.download_file(file_info.file_path)
				with open('settings.ini', 'wb') as new_file:
					new_file.write(downloaded_file)
				test_config = load_config(True)
				if test_config:
					load_config()	
					bot.reply_to(message,"конфиг загрузил и применил")
				else:
					bot.reply_to(message,"почему-то не вышло загрузить конфиг")		
			else:
				bot.send_message(message.from_user.id, 'Не знаю что за файл такой ты мне шлешь. Мне нужен settings.ini.')	
	else:
			bot.reply_to(message, "Кто ты чудовище?")	

def SendToTelegramId(_id,message):
	bot.send_message(_id, message)

def SendToTelegramIdSticker(_id,message):
	bot.send_sticker(_id, message)

def SendToAllTelegram(message):
	for user in telegram_users:
		SendToTelegramId(user.ID, message)

def SendToAllTelegramSticker(message):
	for user in telegram_users:
		SendToTelegramIdSticker(user.ID, message)		

def TelegramBot():
	while True:
		try:
			content = str(requests.get('https://www.proxy-list.download/api/v1/get?type=http').content)
			content = content.replace(r'\r\n',',')
			content = content.replace("b'",'')
			content = content.replace(",'",'')
			a = content.split(',')
			contarr = list(proxylist)
			contarr.extend(a)
		except:
			sleep(0.1)
			continue
		for prox in contarr:
			apihelper.proxy = {'https': prox}
			try:
				bot.polling(none_stop=True)
			except:
				sleep(0.1)

# Main loop dunction
N2Counter = 999999999
N3Counter = 999999999
N4Counter = 0
N5Counter = 0
N6Counter = 0			
def main():
	global N2Counter
	global N3Counter
	global N4Counter
	global N5Counter
	global N6Counter

	# Start keyboart queue thread
	inputQueue = queue.Queue()
	inputThread = threading.Thread(target=read_kbd_input, args=(inputQueue,), daemon=True)
	inputThread.start()

	# Arduino IO queue thread
	ArduinoIOQoueueThread = threading.Thread(target=Arduino.IOQueue, args=(), daemon=True)
	ArduinoIOQoueueThread.start()

	# Check computers thread
	CheckComputersThread = threading.Thread(target=CheckComputersAndBackups, args=(), daemon=True)
	CheckComputersThread.start()

	# Check computers thread
	WatchDogThread = threading.Thread(target=WatchDog_func, args=(), daemon=True)
	WatchDogThread.start()

	#Start Telegram bot thread
	TelegramBotThread = threading.Thread(target=TelegramBot, args=(), daemon=True)
	TelegramBotThread.start()

	# network_things_rebooter = NetworkThingsRebooter(arduino=Arduino, things_rel_number=4)

	while True:
		GPIO.setmode(GPIO.BCM) # говорим о том, что мы будем обращаться к контактам по номеру канала 
		GPIO.setup(17, GPIO.OUT) # Настраиваем GPIO пин 17 на вывод (чтобы мигать светодиодом на крышке)
		GPIO.output(17, True) # Включаем светодиод
		now = datetime.now()
		# Watchdog
		SendToSerial(WatchDogSerial,'~U',False) # Отправка команды "я в норме" на вотчдог

		# *** Блок принятия решений ***
		Alerts.CheckSelf()

		# Перезагрузка сетевого оборудования, если интернет отсутствует
		# network_things_rebooter.check_and_reboot()
		
		# Send alerts
		if Arduino.DCACCVoltage <= 11.1:
			Alerts.SendDCVoltageAlert(Arduino.DCACCVoltage)
		if not Arduino.ACExist and (now-StartTime).total_seconds() > 900:
			Alerts.SendACStatusAlert()	
		
		# Выключение, если аккумуляторы разряжены
		if OffOnDCVoltage and Arduino.DCACCVoltage <= 11:
			if N2Counter < 1200: # Проверяем компы каждый N-ый цикл
				N2Counter +=1
			else:	
				N2Counter = 0
				delay = 500
				Alerts.SendOffServersAlert(delay,'DC loss')
				for comp in servers:
					comp.OffByAdmin = False
					comp.TurnOff(delay)
		else:
			N2Counter = 999999999			

		# Выключение, если нет питания и не рабочее время
		if OffOnTime and not Arduino.ACExist and Arduino.DCACCVoltage <= 12.5 and (now.hour > 19 or now.hour < 6):		
			if N3Counter < 1200: # Проверяем компы каждый N-ый цикл
				N3Counter +=1
			else:
				N3Counter = 0
				delay = 500
				Alerts.SendOffServersAlert(delay,'by AC loss and schedule')
				for comp in servers:
					if comp.PowerState and comp.state and not comp.maintenance:
						comp.OffByAdmin = False
						comp.TurnOff(delay = 500)
		else:
			N3Counter = 999999999			

		# Включение, если выключен и если рабочее время и еще есть заряд аккумулятора
		if OnOnTime and Arduino.DCACCVoltage > 11.6 and not Arduino.ACExist and now.hour > 8 and now.hour < 19:		
			ExistOff = False
			for comp in servers:
				if not comp.state and not comp.PowerState and not comp.OffByAdmin and not comp.maintenance:
					ExistOff = True
			if ExistOff:
				if N4Counter < 1200: # Проверяем компы каждый N-ый цикл
					N4Counter +=1
				else:
					N4Counter = 0
					Alerts.SendOnServersAlert('ON by schedule')
					for comp in servers:
						if not comp.state and not comp.PowerState and not comp.OffByAdmin and not comp.maintenance:
							comp.OnByAdmin = True;
							comp.TurnON()
		else:
			N4Counter = 0

		# Включение, если выключен и если появилось питание на входе
		if OnIfPowerOn and Arduino.ACExist:		
			ExistOff = False
			for comp in servers:
				if not comp.state and not comp.PowerState and not comp.OffByAdmin and not comp.maintenance:
					ExistOff = True
			if ExistOff:
				if N5Counter < 1200: # Проверяем компы каждый N-ый цикл
					N5Counter +=1
				else:
					N5Counter = 0
					Alerts.SendOnServersAlert('ON by power on')
					for comp in servers:
						if not comp.state and not comp.PowerState and not comp.OffByAdmin and not comp.maintenance:
							comp.OnByAdmin = True;
							comp.TurnON()
		else:
			N5Counter = 0

		# Обработка событий ввода с клавиатуры
		if (inputQueue.qsize() > 0):
			input_str = inputQueue.get()

			answer = CommandProcessing(input_str, None, None)
			print(answer)
		sleep(0.1)
		GPIO.setmode(GPIO.BCM) # говорим о том, что мы будем обращаться к контактам по номеру канала 
		GPIO.setup(17, GPIO.OUT) # Настраиваем GPIO пин 17 на вывод (чтобы мигать светодиодом на крышке)
		GPIO.output(17, False) # Выключаем светодиод
		sleep(0.1)	

def load_config(test=False):
	if not test:
		global emails_for_alarm
		global telegram_users
		global servers
		global backups
	_emails_for_alarm = []
	_telegram_users = []
	_servers = []
	_backups = []
	#try:
	config = configparser.ConfigParser()
	config.read(config_path)
	for section in config.sections():  
		for key in config[section]:
			if section == 'emails': 
				_emails_for_alarm.append(config[section][key])
			elif section == 'TelegramAdmins':
				tadmin = config[section][key].split(';')
				_telegram_users.append(TelegramUsersClass(tadmin[0],tadmin[1]))
			elif section == 'backups':
				backup_split = config[section][key].split(';')
				#	(name,IP,port)
				#	[backups]
				#	backup1 = Trade2019full;192.168.19.203;8686
				#	backup2 = Trade2019diff;192.168.19.203;8686
				_backups.append(BaseBackup(backup_split[0],backup_split[1],int(backup_split[2])))	
		if section.startswith('server-'):
			_servers.append(Computer(config[section]['name'],config[section]['ip'],int(config[section]['port']),int(config[section]['rel_number']),int(config[section]['usbstate']),
				Srv1CClass(config[section].getboolean('server1c_exist',fallback=True),config[section]['server1c_user'],config[section]['server1c_pass'],config[section]['server1c_path'])))	
	if not test:
		emails_for_alarm = copy.deepcopy(_emails_for_alarm)
		telegram_users = copy.deepcopy(_telegram_users)
		servers = copy.deepcopy(_servers)
		backups = copy.deepcopy(_backups)	
		return True
	#except:
	#	return False
clear()
create_config()
if os.path.exists(config_path):
	if not load_config():
		print(f'Error load {config_path}')
		sys.exit()		
else:
	print(f'Not exist {config_path}')
	sys.exit()	
InicializeWatchdog()
Arduino.Initialize()
print("I'am ready")

# Start main function
main()
