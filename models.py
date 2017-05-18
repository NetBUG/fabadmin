import ujson as json
from datetime import datetime
from uuid import uuid4

from flask.ext.sqlalchemy import SQLAlchemy
from flask_user import UserMixin


db = SQLAlchemy()


# generate a big random token for user cookies and sessions
def generate_token():
    return str(uuid4())[:50]


# Simple Role implementation, name = [user, admin]
class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), unique=True)

    def create_from_dict(self, data):
        self.name = data["name"]
        super(Role, self).__init__()

    def get_code(self):
        return self.name


# Define the User data model. Make sure to add flask.ext.user UserMixin !!!
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    oauth_id = db.Column(db.Integer, default=-1)
    token = db.Column(db.String(100), unique=True)  # special session and oauth cookie

    # alter table user add column role_id INTEGER REFERENCES role (id);
    # update user set role_id = 1 where role_id is NULL;
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    role = db.relationship('Role', backref=db.backref('role', lazy='dynamic'))

    # User authentication information
    username = db.Column(db.String(50), nullable=False, unique=True)  # TODO: remove or get username from other services
    password = db.Column(db.String(255), nullable=False, server_default='')
    reset_password_token = db.Column(db.String(100), nullable=False, server_default='')

    # User email information
    email = db.Column(db.String(255), nullable=False, unique=True)
    confirmed_at = db.Column(db.DateTime())

    # User information
    active = db.Column('is_active', db.Boolean(), nullable=False, server_default='0')
    first_name = db.Column(db.String(100), nullable=False, server_default='')
    last_name = db.Column(db.String(100), nullable=False, server_default='')
    timezone = db.Column(db.String(100), nullable=True, server_default='UTC')
    max_score = db.Column(db.Integer, default=0)

    # implement this method in all helper models (not for storing user data)
    def create_from_dict(self, data):
        self.oauth_id = data["oauth_id"]
        self.token = generate_token()
        self.username = data["username"]
        self.email = data["email"]
        self.confirmed_at = datetime.utcnow()
        self.active = True
        self.first_name = data["first_name"]
        self.last_name = data["last_name"]
        super(User, self).__init__()

    def get_code(self):
        return self.oauth_id


# Define the Machine data model.
class Machine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    machine_name = db.Column(db.String(160), nullable=True, server_default='Machine')
    machine_type = db.Column(db.String(160), nullable=True, server_default='Machine')
    desc = db.Column(db.VARCHAR)  # description

    def __init__(self, name="", mac_type="", desc=""):
        self.machine_name = name
        self.machine_type = mac_type
        self.desc = desc

    def __repr__(self):
        return '<Machine %r_%r>' % (self.user_id, self.ts)

# Machine usage log entry model
class LogEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref=db.backref('logentry', lazy='dynamic'))
    username = db.Column(db.String(160), nullable=True, server_default='Default')
    task_name = db.Column(db.String(160), nullable=True, server_default='Detail1')
    ts_begin = db.Column(db.DateTime())  # Session start time
    ts_end = db.Column(db.DateTime())  # Session end time
    ts_upd = db.Column(db.DateTime())  # Session last update time

    def __init__(self, user_id, ts, username="", task=""):
        self.ts_begin = ts
        self.ts_upd = ts
        self.user_id = user_id
        self.username = username
        self.task_name = task

    def __repr__(self):
        return '<Session %r_%r>' % (self.user_id, self.ts)


