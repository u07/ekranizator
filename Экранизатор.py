# 
#	https://PetelinSasha.ru
#

print("Загрузка...", end='\r')

# base
import sys,os,re,time,shutil,inspect, ctypes
# ffmpeg
import re, subprocess, asyncio, multiprocessing 
from functools import lru_cache


import pathlib, difflib, tempfile


APP_VER = '03.04.2025'
APP_NAME = 'Экранизатор'
KEY_NAME = 'Экранизатор'
FILETYPES_IMG = ('.jpg', '.jpeg', '.jpe', '.bmp', '.png', '.webp')
FILETYPES_AUDIO = ('.wav', '.mp3', '.flac')
ALLOWED_FILETYPES = FILETYPES_AUDIO + FILETYPES_IMG
REQUIRED_FILES = ('ffmpeg',)
#____________________ ширина консоли 80 символов _______________________________
HELP_STRING = r"""
 Эта утилита переведёт вашу аудиокнигу в видеоформат - статичное видео,   
 состоящее из одной картинки-обложки. Такое видео отличается минимальным  
 размером и подходит для загрузки на rutube/youtube/vk.

 Перетащите папку с аудиокнигой сюда и нажмите Enter. В папке должны быть:

    1) Главы книги в формате wav, flac или mp3, желательно пронумерованные.
	
    2) Картинка для обложки в формате jpg или png

    3) По желанию: аудиофайлы "вступление", "концовка", "отбивка"

"""

class Base:	
	files = []
	output_dir = ''
	errors = False
	terminal_width = 0
	debug = False
	mutex = None
	
	def __init__(self, gather_files=True, clear_console=True, **kwargs):
		sys.excepthook = Base.on_error
		Base.debug = ("--debug" in sys.argv) or ("--debug" in os.path.basename(__file__)) or ("--debug" in os.path.basename(sys.executable))	
		Base.terminal_width = shutil.get_terminal_size().columns - 1
		globals()["log"] = Base.log
		globals()["dbg"] = Base.dbg
		globals()["err"] = Base.err
		os.system(f'title {APP_NAME} v{APP_VER} PetelinSasha.ru')
		dbg("Включена отладка")
		try:
			kernel32 = ctypes.windll.kernel32 
			hStdin = kernel32.GetStdHandle(-10)
			mode = ctypes.c_uint()
			kernel32.GetConsoleMode(hStdin, ctypes.byref(mode))	# активируем контекстное меню в консоли
			kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), mode.value & ~0x0010) # ~ENABLE_MOUSE_INPUT
		except: pass
		if gather_files: self.gather_input_files(**kwargs)
		if clear_console and not Base.errors and not Base.debug: 
			os.system('cls')
	
	@staticmethod
	def on_error(exc_type, exc_value, exc_traceback):
		import traceback
		if exc_type.__name__ != 'KeyboardInterrupt':
			traceback.print_exception(exc_type, exc_value, exc_traceback)
			input(f"\nТысяча чертей! Какая-то дурацкая ошибка. \n\n {exc_value}\n")
		else:
			log("\nПрервано досрочно\n")
		sys.exit(-1)
		
	@staticmethod
	def log(*args, temp=False):
		text = ' '.join(map(str, args))
		# затираем старую исчезающую строку, если была
		print(''.ljust(Base.terminal_width), end='\r')
		# выводим исчезающую строку
		if temp: print(text[:Base.terminal_width].replace('\n', ' '), end='\r')
		# или обычную
		else: print(text)

	@staticmethod
	def dbg(*args):
		if Base.debug: log('|', *args)
	
	@staticmethod	
	def err(*args, fatal=False):
		Base.errors = True
		log(f'ОШИБКА {inspect.currentframe().f_back.f_lineno}', *args)
		if fatal: 
			log("Продолжение невозможно.")
			Base.finish()
		
	@staticmethod
	def input(*args):
		# затираем старую исчезающую строку, если была
		log('', temp = True)
		return input(*args)
	
	@staticmethod
	def finish(text='Готово.', wait=False, text_err='Выполнено, но с ошибками.'):
		Base.release_mutex()
		if Base.errors: log(f"\n{text_err}")
		else: log(f"\n{text}")
		if wait or Base.errors: input()
		else: time.sleep(2)		
		sys.exit()

	@staticmethod
	def wait_another_copy():
		INFINITE = 0xFFFFFFFF
		ERROR_ALREADY_EXISTS = 183
		kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
		Base.mutex = kernel32.CreateMutexW(None, True, f"Global\\PetelinSasha_{APP_NAME}")	
		dbg(f"Получен мьютекс {Base.mutex}, LastErr {kernel32.GetLastError()}")
		if Base.mutex and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
			log("Ожидаю завершения другой копии программы...")
			kernel32.WaitForSingleObject(Base.mutex, INFINITE)
			time.sleep(2)
			
	@staticmethod
	def release_mutex():
		if Base.mutex:
			kernel32 = ctypes.WinDLL('kernel32')
			kernel32.ReleaseMutex(Base.mutex)
			kernel32.CloseHandle(Base.mutex)
			Base.mutex = None
		
	# Собрать переданные файлы, которые требуется обработать. Собираем только разрешённые типы. 
	# Если передан unfold_dirs, вытащим файлы также из переданных папок (можно рекурсивно по желанию).
	# Если передан single_input, все аргументы кроме первого отбрасываются.
	def gather_input_files(self, unfold_dirs=False, recursive=False, single_input=False, **kwargs):
		# Считываем имена входных файлов
		files = [a for a in sys.argv[1:] if not a.startswith("--")]	# из переданных аргументов
		if not files: 												# или из консоли
			args = Base.input(HELP_STRING)	                
			# Причёсываем
			args = re.sub(r'(?<!["\s])([A-Z]:)', r' \1', args)	# Вставляем пробел перед C:, D: если перед ними нет пробела или кавычки (пути склеились)
			files = re.findall(r'".+?"|\S+', args)	# разделяем аргументы по пробелам и кавычкам
		files = [name.strip('\t "') for name in files] # убираем кавычки и концевые пробелы
		dbg("Исходный список файлов: \n   ", "\n    ".join(files))
		# Скрипт ожидает только одно имя файла на вход?
		if single_input: files = files[:1]	
		# Раскрываем папки
		if unfold_dirs:
			for dir in list(filter(os.path.isdir, files)):
				if recursive:
					files.extend(os.path.join(root, f) for root, _, f_list in os.walk(dir) for f in f_list)
				else:
					files.extend(os.path.join(dir, f) for f in os.listdir(dir) if os.path.isfile(os.path.join(dir, f)))
		# Фильтруем, оставляем только разрешённые типы файлов
		files = [
			f for f in files 
			if (os.path.isfile(f) and f.lower().endswith(ALLOWED_FILETYPES)) 
			or (os.path.isdir(f) and '/' in ALLOWED_FILETYPES)
		]
		if not files: 
			err("Нет ни одного подходящего файла.")
			log("Поддерживаются: " + ' '.join(ALLOWED_FILETYPES).replace('/', 'папки'))
			self.finish()
		dbg("Обработанный список файлов: \n   ", "\n    ".join(files))
		Base.output_dir = os.path.dirname(files[0]) if os.path.isfile(files[0]) else files[0]
		dbg("Выходная папка:", Base.output_dir)	
		Base.files = files
		log("")
		return Base.files




# ================================================================ 

class Ffmpeg:	
	MAX_CONCURRENT_TASKS = max(4, multiprocessing.cpu_count())
	
	def __init__(self):
		self.tasks = []
		
	
	@staticmethod
	# Может декодировать строку / кортеж строк
	def decode(data): 
		if isinstance(data, (tuple, list)): 
			return type(data)(decode(s) for s in data)
		return "\n".join(data.decode('utf8', errors='ignore').splitlines()) if data else ""
		#except:	return = "\n".join(data.decode('cp866').splitlines()) todo: зачем?
		
	
	# Узнать через ffmpeg длительность файла/файлов в секундах
	# Если файл не существует или кривой, вернёт ноль.
	def get_duration(self, filepath): 
		if isinstance(filepath, (tuple, list)): return type(filepath)(self.get_duration(s) for s in filepath)
		if not os.path.isfile(filepath): return 0
		text = Ffmpeg.run_cached(f'-hide_banner -i "{filepath}"')
		match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})(?:\.(\d{2}))?", text)
		if match:
			hours, minutes, seconds = map(int, match.groups()[:3])
			milliseconds = int(match.group(4) or 0)
			total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 100
			dbg(f"{os.path.basename(filepath)} длина = {total_seconds} сек.")	
			return total_seconds
		dbg("Длительность не определяется", filepath, text)
		return 0 
		
		
	# Запросить какие-нибудь теги
	def get_tag(self, filepath, tag): 
		if isinstance(filepath, (tuple, list)): return type(filepath)(self.get_tag(s, tag) for s in filepath)
		if not os.path.isfile(filepath): return ""
		text = Ffmpeg.run_cached(f'-hide_banner -i "{filepath}"')
		#	title           : Глава первая - Об авторе
		match = re.search('^ {0,4}' + tag + r'\s*: (.*)', text, re.MULTILINE) # не более 4 пробелов, первый уровень вложенности
		result = match.group(1) if (match and self.not_shit(match.group(1))) else ""
		dbg(f"{os.path.basename(filepath)} {tag} = '{result}'")		
		return result
	
	
	# Тег не испорчен неверной кодировкой?
	def not_shit(self, txt):
		return txt and all(x not in txt for x in "óåûàîýÿèþÐ¾ÐÑ") # уеыаоэяию
			
	
	@staticmethod	
	@lru_cache(256)	
	# Получение информации о файле, результат кешируется
	def run_cached(cmd) -> str:
		try:
			dbg('Запуск ffmpeg', cmd)
			process = subprocess.run(f"ffmpeg {cmd}", capture_output=True, shell=True)
			return Ffmpeg.decode(process.stderr)
		except FileNotFoundError: err("Отсутствует ffmpeg! Без него никак.")
		except Exception as e: err(e)
		return ''
		
		
	# Преобразование сырых данных в другой формат
	def run_raw(self, cmd, data) -> bytes:
		try:
			dbg('Запуск ffmpeg', cmd)
			process = subprocess.Popen(f"ffmpeg {cmd}", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
			stdout, stderr = process.communicate(input=data)
			if process.returncode != 0:	
				err(process.returncode)
				dbg(self.decode(stderr))
			return stdout
		except FileNotFoundError: err("Отсутствует ffmpeg! Без него никак.")
		except Exception as e: err(e)
		return b''
	
	
	# Добавить задачу конвертирования в список
	def add_task(self, name, cmd):
		self.tasks.append((name, cmd))
		
		
	# этот async заставляет писать столько лишних функций...
	async def _worker(self, name, cmd):
		try:
			async with self.sem:
				if name: log(name)
				dbg('Запуск ffmpeg', cmd)				
				process = await asyncio.create_subprocess_shell(f"ffmpeg {cmd}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
				stdout, stderr = await process.communicate()
				if process.returncode != 0: 
					err(process.returncode, self.decode(stderr))
				return(self.decode(stderr))
		except FileNotFoundError: err("Отсутствует ffmpeg! Без него никак.")
		except Exception as e: err(e)		
		
		
	# этот async заставляет писать столько лишних функций...
	async def _run_all_async(self, mp):
		self.sem = asyncio.Semaphore(self.MAX_CONCURRENT_TASKS if mp else 1)
		workers = []		
		for name, cmd in self.tasks:			
			workers.append(self._worker(name, cmd))		
		await asyncio.gather(*workers)
		
		
	# Запустить задачи из списка и дождаться завершения, 
	# mp - многопоточность, число процессов = числу ядер
	def run_all_tasks(self, mp=True):
		asyncio.run(self._run_all_async(mp))
		self.tasks = []





# ================================================================ #


def find_best_match(filenames, keywords):
	best_match = ''
	best_ratio = 0.0	
	for file in filenames:
		stem = pathlib.Path(file).stem.lower()
		for keyword in keywords:
			ratio = difflib.SequenceMatcher(None, stem, keyword).ratio()
			if 0.49 < ratio > best_ratio:
				best_ratio = ratio
				best_match = file
				dbg(f"{stem}|{keyword} = {ratio}")
				if best_ratio >= 0.9: 
					return best_match				
	return best_match      
	

def seconds_to_timestamp(s, ms=False, full=False): 
	h, s = divmod(s, 3600)
	m, s = divmod(s, 60)
	s, z = divmod(s, 1)
	return (f"{int(h):02}:" if h or full else "") + \
		   (f"{int(m):02}:{int(s):02}") + \
		   (f",{int(z*1000):03}" if ms else "")


def sanitize_title(text, long=60, human=True):
	if human: badsym = str.maketrans({'\t':'|', '\r':' ', '\n':' '})
	else: badsym = str.maketrans({'\t':'|', '\r':' ', '\n':' ', '=':'\=', ';':'\;', '#':'\#', '\\':'\\\\'})	
	return text[:long].strip().translate(badsym) + (".." if len(text) > long else "")	


def sanitize_filename(text, long=70):
	text = re.sub(r'[<>:\&\$"/\\|?*\x00-\x1F]', '', text)
	return text[:long]


def tmp_name(f, ext=''):
	if isinstance(f, list):  return [tmp_name(x, ext) for x in f]
	tmp_dir = os.path.join(tempfile.gettempdir(), "ekrnztr")
	os.makedirs(tmp_dir, exist_ok=True)
	if not f: return ""
	shortname = os.path.basename(f)
	return os.path.join(tmp_dir, f"{os.path.basename(f)}{ext}")
	
	
def tmp_cleanup():
	tmp_dir = os.path.join(tempfile.gettempdir(), "ekrnztr")
	if not os.path.isdir(tmp_dir): return
	for f in os.listdir(tmp_dir):
		dbg('Удаляю временный файл ' + f)
		os.remove(os.path.join(tmp_dir, f))		
	#os.rmdir(tmp_dir)


# ================================================================ #


base = Base(single_input = True, unfold_dirs=True)
ffmpeg = Ffmpeg()


# Ищем музыкальные вставки
log("...изучаю содержимое...", temp=True)

files_audio = [f for f in base.files if f.lower().endswith(FILETYPES_AUDIO)]
files_img = [f for f in base.files if f.lower().endswith(FILETYPES_IMG)]

kw_bridge = ["перебивка", "переход", "отбивка", "разделитель", "проигрыш", "встав)ка", "музыка", 
			 "джингл", "music", "interlude", "transition", "segue", "bumper", "stinger", "jingle", 
			 "bridge", "cortinilla", "intermezzo", "stacco", "uberleitung"]

kw_intro = ["начало", "опенинг", "заст*ав ка", "int*r*_o", "вступлен=ие",  
			"beginning", "opening", "start", "начало главы", "nachalo"]

kw_outro = ["конец", "окончание", "заверше-ние", "out-r- o", "эндинг", "ending", "final", 
			"end music", "конец главы", "концов-к_а", "konec", "closing"]
	
bridge = find_best_match(files_audio, kw_bridge)
intro = find_best_match(files_audio, kw_intro)
outro = find_best_match(files_audio, kw_outro)

bridge_dur = ffmpeg.get_duration(bridge)
intro_dur = ffmpeg.get_duration(intro)
outro_dur = ffmpeg.get_duration(outro)

if bridge in files_audio: files_audio.remove(bridge)
if intro in files_audio: files_audio.remove(intro)	
if outro in files_audio: files_audio.remove(outro)


# Ищем обложку
if files_img:
	picture = files_img[0]  
else:
	picture = None
	err("В указанной папке нет ни одной картинки для обложки.")
	log("Поддерживаются файлы: " + ' '.join(FILETYPES_IMG))
	base.finish()

	
# Ищем главы книги
# Сначала ищем главы с цифровыми обозначениями "01 - Пролог.wav". Если таких нет, берём всё подряд.
audio = ([f for f in files_audio if os.path.basename(f)[0].isdigit()]  or  files_audio)

if not audio: 
	err("В указанной папке нет аудиозаписей.")
	log("Поддерживаются файлы: " + ' '.join(FILETYPES_AUDIO))
	base.finish()
	
# Естественная сортировка номеров глав: 1,2,3...10,11,12
audio.sort(key=lambda s: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s)])
	
audio_durs = ffmpeg.get_duration(audio)			# приблизительные! длительности (Mp3 плохо определяется)
audio_titles = ffmpeg.get_tag(audio, "title")	# названия глав, если есть

book_name = ", ".join(dict.fromkeys(ffmpeg.get_tag(audio, "album"))) or os.path.basename(base.output_dir) # название книги/книг
book_author = ", ".join(dict.fromkeys(ffmpeg.get_tag(audio, "artist"))) # автор или авторы, если сборник
book_reader = ", ".join(dict.fromkeys(ffmpeg.get_tag(audio, "album_artist"))) or \
			  ", ".join(dict.fromkeys(ffmpeg.get_tag(audio, "comment"))) # литрес пишет чтеца в комменты

total_dur = int(sum(audio_durs) + intro_dur + outro_dur + bridge_dur * (len(audio) - 1) + 3) # три запасных секунды тишины в конец
total_mb = 1 + total_dur * 75 / 8 / 1024 # Результирующий битрейт ожидается от 64 до 80 кбит/с


### Рассказываем, что нашли
log("Содержимое папки: \n")
if intro:   log(f' - Заставка: "{os.path.basename(intro)}" / {intro_dur} сек.')
if bridge:  log(f' - Отбивка: "{os.path.basename(bridge)}" / {bridge_dur} сек.')
if outro:   log(f' - Концовка: "{os.path.basename(outro)}" / {outro_dur} сек.')
log(f' - Обложка: "{os.path.basename(picture)}"')
log(f' - Главы книги: {len(audio)} шт.')

for row in zip(audio, audio_durs, audio_titles):
	dbg(*row)

log("\n" + f"Получится видео длиной {seconds_to_timestamp(total_dur)} и весом {total_mb:.0f} Мб.")
input("\nНажмите Enter, чтобы начать.\n")
Base.wait_another_copy()
tmp_cleanup()
time_start = time.time()


### Конвертируем все аудио в Opus
loglevel = "verbose" if base.debug else "error"
tmp_audio = tmp_name(audio, ext='.opus')
tmp_intro = tmp_name(intro, ext='.opus')
tmp_outro = tmp_name(outro, ext='.opus')
tmp_bridge = tmp_name(bridge, ext='.opus')

for f, tmp_f in zip([intro, outro, bridge] + audio, [tmp_intro, tmp_outro, tmp_bridge] + tmp_audio):
	if not f: continue
	cmd = f'-y -hide_banner -loglevel {loglevel} -i "{f}" -c:a libopus -ac 1 -b:a 64K -f ogg -vn "{tmp_f}"'
	ffmpeg.add_task(f"Конвертирую {os.path.basename(f)}...", cmd)

ffmpeg.run_all_tasks()

log("Уточняю длину...")

audio_durs = ffmpeg.get_duration(tmp_audio) # Уточняем длину, т.к. mp3 vbr определяется сильно неточно
total_dur = int(sum(audio_durs) + intro_dur + outro_dur + bridge_dur * (len(audio) - 1) + 3) # три секунды в запас


### Создаём видеодорожку нужной длины      

tmp_video = tmp_name('ekr-tmp-vid.mp4')

# слишком редкие ключевые кадры = медленная перемотка. Ставим один хотя бы раз в 20 минут. Лучше конечно 10, но это удручающе на размер влияет
cmd = f'-y -hide_banner -loglevel {loglevel} -r 0.3 -i "{picture}" -vf "scale=w=if(gt(iw*ih\,1920*1080)\,iw*min(1920/iw\,1920/ih)\,iw):h=-2:in_range=full:out_range=limited, pad=ceil(iw/2)*2:ceil(ih/2)*2, tpad=stop_mode=clone:stop_duration=3600100" -an -c:v libx264 -pix_fmt yuv420p -preset faster -x264-params "rc-lookahead=1:keyint=360:min-keyint=180:ref=0:subme=0:no-scenecut=1:bframes=0:qp=20" -bsf:v filter_units=remove_types=6 -frag_duration 1800111222 -t {total_dur} "{tmp_video}"'



ffmpeg.add_task("Готовлю видеодорожку...", cmd)
ffmpeg.run_all_tasks()


### Накидываем плейлист для будущей аудиодорожки
tmp_alist = tmp_name('ekr-tmp-aud.txt')

with open(tmp_alist, 'w', encoding="utf-8") as file:
	if intro: file.write(f"file '{tmp_intro}'" + "\n")
	for i, a in enumerate(tmp_audio):
		file.write(f"file '{a}'" + "\n")
		if bridge and (i != len(tmp_audio)-1):
			file.write(f"file '{tmp_bridge}'" + "\n")
	if outro: file.write(f"file '{tmp_outro}'")


### Готовим оглавления, 2 шт
tmp_toc = tmp_name('ekr-tmp-toc.txt')
human_toc = os.path.join(base.output_dir, "Оглавление.txt")

with open(tmp_toc, 'w', encoding="utf-8") as toc, open(human_toc, 'w', encoding="utf-8") as htoc:
	toc.write(";FFMETADATA1" + "\n")
	if book_name: toc.write("title=" + sanitize_title(book_name, human=False, long=512) + "\n")
	if book_name: toc.write("album=" + sanitize_title(book_name, human=False, long=512) + "\n")
	if book_author: toc.write("artist=" + sanitize_title(book_author, human=False, long=512) + "\n")	
	if book_reader: toc.write("album_artist=" + sanitize_title(book_reader, human=False, long=512) + "\n")
	toc.write("genre=Аудиокнига" + "\n")
	toc.write(f"comment=Encoder: {APP_NAME} v{APP_VER} PetelinSasha.ru" + "\n")	
	
	cur_pos = intro_dur if intro else 0
	for f, dur, title in zip(audio, audio_durs, audio_titles):
		# # chars ‘=’, ‘;’, ‘#’, ‘\’ and a newline must be ‘\’ escaped
		
		# [CHAPTER]
		# TIMEBASE=1/1000
		# START=0 название в конец, тк видно только две строчки!
		# END=30000
		# title=001
		if bridge: dur += bridge_dur
		title_ = title or 'Глава '+os.path.splitext(os.path.basename(f))[0]
		toc.write("[CHAPTER]" + "\n")	
		toc.write("TIMEBASE=1/100" + "\n")	
		toc.write(f"START={int((cur_pos)*100)}" + "\n")
		toc.write(f"END={int((cur_pos + dur)*100)}" + "\n")
		toc.write(f'title="{sanitize_title(title_, human=False)}"' + "\n\n")				
		htoc.write(f"{seconds_to_timestamp(cur_pos)} {sanitize_title(title_)}"  + "\n")	
		cur_pos += dur
		
	htoc.write("\n")
	if book_author: htoc.write(sanitize_title(book_author, long=1024) + "\n")
	if book_name: htoc.write(sanitize_title(book_name, long=1024) + " [Аудиокнига]" + "\n")
	if book_reader: htoc.write("Читает " + sanitize_title(book_reader, long=1024) + "\n")


### Объединяем аудио с видео 
the_result = os.path.join(base.output_dir, sanitize_filename(book_name) + ".mp4")

# Дллина mp4-сегмента тоже максимум полчаса, иначе через 10 часов сплошного видео скорость кодирования упадёт втрое
cmd = f'-y -hide_banner -loglevel {loglevel} -i "{tmp_toc}" -i "{tmp_video}" -f concat -safe 0 -i "{tmp_alist}" -c:v copy -c:a copy -movflags +faststart -frag_duration 1800111222 -t {int(total_dur)} "{the_result}"'

ffmpeg.add_task("Сохраняю результат...", cmd)

ffmpeg.run_all_tasks()


### Спасибо, приходите ещё
time_exec = time.time() - time_start
ratio = max(total_dur, 0.1) / max(time_exec, 0.1)
dbg("Временные файлы сохранены в " + tmp_name("..."))
if not base.debug: tmp_cleanup()

base.finish(text = '\n' + f'Готово. Затрачено времени {seconds_to_timestamp(time_exec)}, скорость х {int(ratio)}', wait=True)













