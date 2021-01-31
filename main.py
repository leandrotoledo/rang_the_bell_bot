import datetime
import logging
import sqlite3
from os import getenv
from queue import Queue
from sqlite3 import Error
from threading import Thread

import paho.mqtt.client as mqtt
from emoji import emojize
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CommandHandler
from telegram.ext import Updater, CallbackQueryHandler

from defs import *

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)


class TelegramBot(object):
    def __init__(self, token, queue, mqtt_client):
        self.token = token
        self.queue = queue
        self.mqtt_client = mqtt_client

        self.db = None
        self.updater = None

        try:
            self.db = sqlite3.connect(getenv('DB_FILE'), check_same_thread=False)
            if getenv('DB_DEBUG'):
                self.db.set_trace_callback(logging.info)

            self.cursor = self.db.cursor()
            self.cursor.execute(DB_INIT_SQL)
            logger.info('[SQLite] Connected to the database')
        except Error as e:
            logger.critical('[SQLite] Error: %s' % e)
        finally:
            if self.db:
                self.db.commit()

        thread = Thread(target=self.run, args=())
        thread.daemon = True

        logging.info('[Telegram] Starting TelegramBot thread...')

        thread.start()

    def she_rang_the_bell(self, client, userdata, msg):
        logger.info('[MQTT] Received from: %s - Payload: %s' % (msg.topic, msg.payload))

        sql = """
            SELECT handled_by, created_on 
            FROM logs WHERE handled_by IS NOT NULL AND created_on > date('now') ORDER BY id DESC LIMIT 1;"""
        self.cursor.execute(sql)
        data = self.cursor.fetchone()

        sql = """INSERT INTO logs ('event', 'trigger', 'state', 'created_on') VALUES (?, ?, ?, ?);"""
        self.cursor.execute(sql, (EVENT.RING, TRIGGER.TARLY, STATE.INITIATED, datetime.datetime.now()))
        log_id = self.cursor.lastrowid

        text = emojize(':bell: _She rang the bell\!_ :bell:\n\n', use_aliases=True)

        if data:
            last_handled_by, created_on = data
            created_on = datetime.datetime.strptime(created_on, '%Y-%m-%d %H:%M:%S.%f')

            text += 'Looks like *%s* took her out last at *%s*\.' % (last_handled_by, created_on.strftime('%I:%M %p'))

        reply_keyboard = [
            [InlineKeyboardButton(
                emojize(':white_check_mark: I\'ll take her out', use_aliases=True), callback_data=CALLBACK.TAKE_HER_OUT
            )],
            [InlineKeyboardButton(
                emojize(':x: Dismiss', use_aliases=True), callback_data=CALLBACK.DISMISS + '#' + str(log_id)
            )]
        ]

        message = self.updater.bot.send_message(
            chat_id=getenv('TELEGRAM_CHAT_ID'),
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(reply_keyboard)
        )

        sql = """UPDATE logs SET message_id = ? WHERE id = ?"""
        self.cursor.execute(sql, (message.message_id, log_id))

        self.db.commit()

    def take_her_out(self, update, context):
        text = emojize(':paw_prints: %s took her out...')

        # Handle Inline Keyboard Button Reply
        if hasattr(update, 'callback_query') and update.callback_query:
            query = update.callback_query
            query.answer()

            user = query.from_user.first_name
            user_id = query.from_user.id
            message_id = query.message.message_id

            logger.info('[Telegram] (Button Reply) take_her_out - %s selected "%s"' % (user, query.data))
            query.edit_message_text(text=text % user)

            sql = """UPDATE logs SET handled_by = ?, state = ? WHERE message_id = ?"""
            self.cursor.execute(sql, (user, STATE.CLAIMED, message_id))

        # Handle Command /take
        else:
            user = update.message.from_user.first_name
            user_id = update.message.from_user.id
            message_id = update.message.message_id

            logger.info('[Telegram] (Manually Initiated) take_her_out - %s sent "%s"' % (user, update.message.text))
            update.message.reply_text(text=text % user)

            sql = """
                INSERT INTO logs (
                    'event', 'trigger', 'message_id', 'handled_by', 'state', 'created_on') VALUES (?, ?, ?, ?, ?, ?);"""
            self.cursor.execute(sql,
                                (EVENT.RING, TRIGGER.MANUAL, message_id, user, STATE.CLAIMED, datetime.datetime.now()))

        self.db.commit()

        logger.info('[MQTT] Publish on: %s - Payload: %s' % (MQTTTOPIC.TAKE_HER_OUT, user))
        self.mqtt_client.publish(MQTTTOPIC.TAKE_HER_OUT, user)

        current_jobs = context.job_queue.get_jobs_by_name(str(message_id))
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_once(self.send_survey, getenv('TELEGRAM_SURVEY_DELAY'),
                                   context={'user': user, 'user_id': user_id, 'message_id': message_id},
                                   name=str(message_id))

    def send_survey(self, context):
        user = context.job.context['user']
        user_id = str(context.job.context['user_id'])
        message_id = context.job.context['message_id']

        reply_keyboard = [
            [InlineKeyboardButton(
                emojize(':sweat_drops: #1', use_aliases=True),
                callback_data='#'.join((CALLBACK.RECORD_SURVEY, RESULT.NUMBER_1, str(message_id)))
            )],
            [InlineKeyboardButton(
                emojize(':poop: #2', use_aliases=True),
                callback_data='#'.join((CALLBACK.RECORD_SURVEY, RESULT.NUMBER_2, str(message_id)))
            )],
            [InlineKeyboardButton(
                emojize(':sweat_drops: Both :poop:', use_aliases=True),
                callback_data='#'.join((CALLBACK.RECORD_SURVEY, RESULT.BOTH, str(message_id)))
            )],
            [InlineKeyboardButton(
                emojize(':rage: Nothing :rage:', use_aliases=True),
                callback_data='#'.join((CALLBACK.RECORD_SURVEY, RESULT.NOTHING, str(message_id)))
            )]
        ]

        context.bot.send_message(
            chat_id=getenv('TELEGRAM_CHAT_ID'),
            text="[{}](tg://user?id={}), what did she do?".format(user, user_id),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(reply_keyboard)
        )

        sql = """UPDATE logs SET state = ? WHERE message_id = ?"""
        self.cursor.execute(sql, (STATE.SURVEYED, message_id))

        self.db.commit()

    def record_survey(self, update, context):
        query = update.callback_query
        query.answer()

        _, answer, message_id = query.data.split('#')
        user = query.from_user.first_name

        logger.info('[Telegram] record_survey - %s chose "%s"' % (user, answer))
        query.delete_message()

        sql = """UPDATE logs SET state = ?, result = ? WHERE message_id = ?"""
        self.cursor.execute(sql, (STATE.COMPLETED, answer, message_id))

        self.db.commit()

    def dismiss(self, update, context):
        query = update.callback_query
        query.answer()

        _, log_id = query.data.split('#')
        user = query.from_user.first_name

        logger.info('[Telegram] dismiss - %s dismissed log id %s' % (user, log_id))
        query.delete_message()

        sql = """UPDATE logs SET state = ? WHERE id = ?"""
        self.cursor.execute(sql, (STATE.DISMISSED, log_id))

        self.db.commit()

    def report(self, update, context):
        user = update.message.from_user.first_name
        logger.info('[Telegram] report requested by %s' % user)

        text = ''

        # Number of time(s) she's been taken out
        sql = """
            SELECT COUNT(event) FROM logs 
            WHERE created_on > date('now') AND state = ?"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        taken_out_count = self.cursor.fetchone()
        if taken_out_count and taken_out_count[0] > 0:
            text += emojize('\n\n*How many time(s) was she taken out today?*\n', use_aliases=True)
            text += '   She was taken out *{} time(s)*'.format(*taken_out_count)

        # Breakdown - Trigger: Bell Rang vs Manual
        sql = """
            SELECT COUNT(event), trigger FROM logs 
            WHERE created_on > date('now') AND state = ? GROUP BY trigger ORDER BY 2 DESC"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        rows = self.cursor.fetchall()
        if rows:
            for row in rows:
                text += '\n'
                if row[1] == TRIGGER.TARLY:
                    text += '       \- _She rang the bell *%d time(s)*_' % row[0]
                elif row[1] == TRIGGER.MANUAL:
                    text += '       \- _She was taken out *%d time(s)* without ringing the bell_' % row[0]

        # Number of time(s) bell was dismissed.
        sql = """
            SELECT COUNT(event) FROM logs 
            WHERE created_on > date('now') AND state = ? GROUP BY state"""
        self.cursor.execute(sql, (STATE.DISMISSED,))
        dismissed_count = self.cursor.fetchone()
        if dismissed_count:
            text += '\n'
            text += '       \- _{} notifications were dismissed_'.format(*dismissed_count)

        # Breakdown - Trigger: Handled By
        sql = """
            SELECT handled_by, COUNT(event) FROM logs 
            WHERE created_on > date('now') AND state = ? GROUP BY handled_by ORDER BY 2 DESC"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        rows = self.cursor.fetchall()
        if rows:
            text += emojize('\n\n*Who\'s taken her out today?*', use_aliases=True)
            for row in rows:
                text += '\n   *{}* took her out {} time(s)'.format(*row)

        # Last time she's been taken out
        sql = """
            SELECT handled_by, result, created_on FROM logs 
            WHERE created_on > date('now') AND state = ? ORDER BY id DESC LIMIT 1"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        last_taken_out = self.cursor.fetchone()
        last_taken_out_by = None
        if last_taken_out:
            text += emojize('\n\n*Who took her out last?*\n', use_aliases=True)

            last_taken_out_by = last_taken_out[0]
            last_taken_out_on = datetime.datetime.strptime(last_taken_out[2], '%Y-%m-%d %H:%M:%S.%f')
            text += '   *{}* took her out last at *{:%I:%M %p}*'.format(last_taken_out_by, last_taken_out_on)

        # What did she do last time she's been taken out?
        sql = """
            SELECT result, created_on FROM logs 
            WHERE created_on > date('now') AND state = ? ORDER BY id DESC LIMIT 1"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        last_taken_out = self.cursor.fetchone()
        if last_taken_out:
            text += emojize('\n\n*What did she do the last time she was taken out?*\n', use_aliases=True)
            if last_taken_out[0] == RESULT.NUMBER_1:
                text += emojize('   :sweat_drops:', use_aliases=True)
            elif last_taken_out[0] == RESULT.NUMBER_2:
                text += emojize('   :poop:', use_aliases=True)
            elif last_taken_out[0] == RESULT.BOTH:
                text += emojize('   :sweat_drops::poop:', use_aliases=True)
            elif last_taken_out[0] == RESULT.NOTHING:
                text += emojize('   :rage:', use_aliases=True)

        # Who takes her out next
        if last_taken_out_by:
            sql = """
                SELECT handled_by FROM logs 
                WHERE created_on > date('now') AND state = ? AND handled_by != ? ORDER BY id DESC LIMIT 1"""
            self.cursor.execute(sql, (STATE.COMPLETED, last_taken_out_by))
            next_to_take = self.cursor.fetchone()
            if next_to_take:
                text += emojize('\n\n*Who takes her out next?*\n', use_aliases=True)
                text += '   *{}*'.format(*next_to_take)

        # Breakdown - What did she do?
        sql = """
            SELECT result, COUNT(event) FROM logs 
            WHERE created_on > date('now') AND state = ? GROUP BY result"""
        self.cursor.execute(sql, (STATE.COMPLETED,))
        rows = self.cursor.fetchall()
        if rows:
            text += emojize('\n\n*What did she do so far?*\n', use_aliases=True)
            for row in rows:
                if row[0] == RESULT.NUMBER_1:
                    text += '   *\#1*: {} time(s)'.format(row[1])
                elif row[0] == RESULT.NUMBER_2:
                    text += '   *\#2*: {} time(s)'.format(row[1])
                elif row[0] == RESULT.BOTH:
                    text += '   *Both*: {} time(s)'.format(row[1])
                elif row[0] == RESULT.NOTHING:
                    text += '   *Nothing*: {} time(s)'.format(row[1])
                text += '\n'

        if not text:
            update.message.reply_text('Not enough data for a report yet. Try again later.')
            return

        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    def run(self):
        self.updater = Updater(token=self.token, use_context=True)

        self.updater.dispatcher.add_handler(
            CommandHandler('take', self.take_her_out))
        self.updater.dispatcher.add_handler(
            CommandHandler('report', self.report))
        self.updater.dispatcher.add_handler(
            CallbackQueryHandler(self.take_her_out, pattern='^' + CALLBACK.TAKE_HER_OUT + '$'))
        self.updater.dispatcher.add_handler(
            CallbackQueryHandler(self.record_survey, pattern='^' + CALLBACK.RECORD_SURVEY))
        self.updater.dispatcher.add_handler(
            CallbackQueryHandler(self.dismiss, pattern='^' + CALLBACK.DISMISS))

        self.updater.start_polling()

    def shutdown(self):
        self.updater.stop()


def on_connect(client, userdata, flags, rc):
    logging.info('[MQTT] Connected with result code (%s)' % str(rc))
    client.subscribe(MQTTTOPIC.RANG_THE_BELL)


def main():
    queue = Queue()
    client = mqtt.Client()

    bot = TelegramBot(getenv('TELEGRAM_TOKEN'), queue, client)

    client.on_connect = on_connect
    client.on_message = bot.she_rang_the_bell
    client.connect(getenv('MQTT_BROKER'))

    logging.info('[MQTT] Starting MQTT loop...')
    client.loop_forever()


if __name__ == '__main__':
    main()
