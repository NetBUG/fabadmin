#!/usr/bin/env python
# coding=utf-8
# Laboratory resource usage monitoring application
# Created on 14.05.2017
# @author Oleg Urzhumtsev

import os.path
import ujson as json

from flask import Flask, make_response, url_for, redirect, render_template, request
from flask_mail import Mail
from flask_user import current_user, UserManager, SQLAlchemyAdapter
import pytz
import yaml
import redis
import requests

from adminview import blueprint as admin_blueprint
#from profile import blueprint as profile_blueprint
#from profile import check_id, get_timezone
from models import *


config_path = 'common/config.yaml'
config_key = 'fabadmin'
with open(config_path, 'r') as f:
    conf = yaml.load(f)
    dbhost = conf[config_key]["DATABASE_HOST"]


# Use a Class-based config to avoid needing a 2nd file
# os.getenv() enables configuration through OS environment variables
class ConfigClass(object):
    # Flask settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'lWxOiKqKPNwJmSldbiSkEbkNjgh2uRSNAb+SK00P3R')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', dbhost)
    # SQLALCHEMY_ECHO = True  # print all SQL requests
    CSRF_ENABLED = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-Mail settings
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', 'reg@skuuper.com')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', 'SophisticatedRegistrator69')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', '"Skuuper Game" <reg@skuuper.com>')
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.zone.ee')
    MAIL_PORT = int(os.getenv('MAIL_PORT', '465'))
    MAIL_USE_SSL = int(os.getenv('MAIL_USE_SSL', True))

    # Flask-User settings
    USER_APP_NAME = 'Skuuper Games'  # Used in email templates
    UPLOAD_FOLDER = '/tmp'

    # Custom variables
    DATABASE_TYPE = conf[config_key]["DATABASE_TYPE"]
    SESSION_DURATION = conf[config_key]["SESSION_DURATION"]
    BONUS_TIMEOUT = conf["BONUS_TIMEOUT"]


def create_app():
    """ Flask application factory """
    app = Flask(__name__)
    app.config.from_object(__name__ + '.ConfigClass')
    app.config.update(
        DEBUG=True,
        FILES_ROOT='./',
    )
    app.register_blueprint(admin_blueprint)
    #app.register_blueprint(profile_blueprint)

    db.app = app
    db.init_app(app)
    db.create_all()

    # Setup Flask-User
    db_adapter = SQLAlchemyAdapter(db, User)  # Register the User model
    wordstat_db_adapter = SQLAlchemyAdapter(db, GameStatsWordOrder)  # Register the Game Stats model
    user_manager = UserManager(db_adapter, app)  # Initialize Flask-User
    db.session.commit()
    return app


app = create_app()
mail = Mail(app)


def change_tz(user, time):
    tz = pytz.timezone(current_user.timezone)
    return time.replace(tzinfo=pytz.timezone('UTC')).astimezone(tz)


@app.route('/')
def main():
    resp = make_response(render_template('index.html'))
    # track all users
    cookie = request.cookies.get("token", None)
    if not cookie:
        resp.set_cookie("token", generate_token())
    resp.set_cookie("anonymous", str(get_user_state()))
    return resp


# TODO: move this auth-API to class

def get_new_token(code):
    return requests.post(
        "http://api.skuuper.com/oauth/token",
        data={
            "client_id": conf["APP_ID"],
            "client_secret": conf["APP_SERCRET"],
            "redirect_uri": "http://gw.skuuper.com/finish_login",
            "grant_type": "authorization_code",
            "code": code
        })


def refresh_token(rf_token=None):
    if not rf_token:
        rf_token = request.cookies.get("refresh_token", None)
    if rf_token:
        return requests.post(
            "http://api.skuuper.com/oauth/token",
            data={
                "client_id": conf["APP_ID"],
                "client_secret": conf["APP_SERCRET"],
                "redirect_uri": "http://gw.skuuper.com/finish_login",
                "grant_type": "refresh_token",
                "refresh_token": rf_token
            })
    else:
        return None


def about_me(ac_token=None):
    if ac_token:
        access_token = ac_token
    else:
        access_token = request.cookies.get("access_token", None)
    if access_token:
        headers = {
            "Authorization": "Bearer {0}".format(access_token)
        }
        return requests.get("http://api.skuuper.com/users/me", headers=headers).json()
    else:
        return {}


def get_user_state():
    """
    :returns 1: user is anonymous
             0: user is logged in
    """
    user_id = check_id(request)
    state = db.session.query(User).filter_by(id=user_id)
    if state.count() > 0:
        if state.first().oauth_id == -1:
            return 1
        else:
            return 0
    else:
        return 1


def process_login(resp, data):
    resp.set_cookie("access_token", data["access_token"])
    if "refresh_token" in data:
        resp.set_cookie("refresh_token", data["refresh_token"])

    # get data about new user
    token = request.cookies.get("token", None)
    if not token:
        token = generate_token()

    about = about_me(data["access_token"])
    print "About:\n", about, "\n---------"
    about = about["user"]

    # load current role (from out OAuth provider)
    try:
        rn = about["role_names"][0]
    except IndexError:
        rn = "user"
    try:
        r = db.session.query(Role).filter_by(name=rn).first()
    except Exception as e:
        print "Unknown role query exception:", e
        r = db.session.query(Role).filter_by(name="user").first()

    # load real user (from out OAuth provider)
    real_user = db.session.query(User).join(User.role).filter(User.email==about["email"])
    if not real_user or real_user.count() == 0:
        tz = get_timezone(request)
        # create absolutely new user with another token
        s = User(oauth_id=about["id"], token=generate_token(), username=about["email"], email=about["email"],
                 first_name=about["given_name"], last_name=about["family_name"], role_id=r.id,
                 timezone=tz, confirmed_at=datetime.now(), active=True)
        db.session.add(s)
        db.session.commit()
        real_user = db.session.query(User).join(User.role).filter(User.email==about["email"])

    real_user = real_user.first()
    resp.set_cookie("token", real_user.token)

    # check & update user role
    if real_user.role.name != rn:
        real_user.role_id = r.id

    if not real_user.is_active:
        real_user.is_active = True

    # merge data from temporary to real user
    tmp_usr = User.query.filter(User.token == token, User.email != about["email"])  # load temporary user, not real
    if tmp_usr and tmp_usr.count() == 1:
        tmp_usr = tmp_usr.first()
        if tmp_usr.max_score > real_user.max_score:
            real_user.max_score = tmp_usr.max_score

        db.session.query(GameStatsWordOrder).filter_by(user_id=tmp_usr.id).update({"user_id": real_user.id})
        db.session.query(Achievements).filter_by(user_id=tmp_usr.id).update({"user_id": real_user.id})

        # remove temporary user
        db.session.delete(tmp_usr)
        db.session.commit()
    return resp


@app.route('/finish_login')
def finish_login():
    resp = make_response(redirect(url_for("main")))
    code = request.args.get("code", None)
    if code:
        resp.set_cookie("code", code)
        r = get_new_token(code)
        try:
            data = r.json()
            print "DATA=", data
            resp = process_login(resp, data)
        except Exception as e:
            print "Exc:", e, "| refreshing token..."
            r = refresh_token()
            data = r.json()
            print "DATA=", data
            resp = process_login(resp, data)
    return resp


# change cookie and logout user from our system
@app.route('/logout')
def logout():
    resp = make_response(redirect("http://api.skuuper.com/users/sign_out?redirect_url=http://gw.skuuper.com/"))
    resp.set_cookie("token", generate_token())
    return resp


@app.route('/check_user.json')
def check_user():
    return json.dumps({"anonymous": get_user_state()})


# test Rails data
@app.route('/test')
def ttt():
    return json.dumps(about_me())


"""
@api {get} /leaderboard.json?page=:page Get top user list ordered by high score, 5 users per page (cached data in Redis)
@apiName GetLeaders
@apiGroup GameBackend
@apiVersion 0.1.1

@apiParam {Number} [page=1] Page of the leaderboard, first by default

@apiSuccess {Object[]} leaders  List of top users
@apiSuccess {String} leaders.username  Public username
@apiSuccess {Number} leaders.max_score  The user's max score

"""
@app.route('/leaderboard.json')
def get_leaders():
    try:
        page = int(request.args.get('page', '1'))
    except:
        page = 1
    try:
        leaders = redis_cache.get("leaders_{0}".format(page))  # data is already dumped
    except Exception as e:
        print "/leaderboard.json exception caught:", e
        leaders = None
    if not leaders:
        leaders = "[]"
    return leaders


"""
@api {get} /machine_client.json Shows state of a the machine  
@apiName Interface_machine
@apiGroup MachineBackend
@apiVersion 0.1.1

@apiSuccess {Object[]} leaders  List of top users
@apiSuccess {String} leaders.username  Public username
@apiSuccess {Number} leaders.max_score  The user's max score

"""
@app.route('/machine_client.json')
def get_machine():
    try:
        page = int(request.args.get('page', '1'))
    except:
        page = 1
    return page

"""
@api {post} /machine_client.json Sets state of the specific machine (user name) and updates the timetamp
@apiName Interface_machine
@apiGroup MachineBackend
@apiVersion 0.1.1

@apiParam {String} [username=1] Set the name of active user
@apiParam {String} [taskname=1] Set the name of the task

@apiSuccess {Object[]} leaders  List of top users
@apiSuccess {String} leaders.username  Public username
@apiSuccess {Number} leaders.max_score  The user's max score

"""
@app.route('/machine_client.json', methods=['POST'])
def set_machine():
    return get_machine()

@app.route('/')
def get_machine():
    try:
        page = int(request.args.get('page', '1'))
    except:
        page = 1
    try:
        leaders = redis_cache.get("leaders_{0}".format(page))  # data is already dumped
    except Exception as e:
        print "/leaderboard.json exception caught:", e
        leaders = None
    if not leaders:
        leaders = "[]"
    return leaders

if __name__ == '__main__':
    # Create all database tables
    # print app.url_map  # some debug
    app.run(host='0.0.0.0', port=5100, debug=True)
