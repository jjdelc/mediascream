import math
import json
from io import StringIO
from datetime import datetime
import xml.etree.ElementTree as etree
from flask import Flask, render_template, request

from photolog import web_logger as log, settings_file
from photolog.db import DB
from photolog.settings import Settings
from photolog.squeue import SqliteQueue

settings = Settings.load(settings_file)
db = DB(settings.DB_FILE)
queue = SqliteQueue(settings.DB_FILE)
app = Flask(__name__)

PAGE_SIZE = 24


def human_size(size):
    size_name = ['B', 'KB', 'MB', 'GB']
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 2)
    if s > 0:
        return '%s%s' % (s, size_name[i])
    return '0B'


def get_paginator(total, page_size, current):
    total_pages = math.ceil(total / page_size)
    next_page = current + 1 if current < total_pages else None
    prev_page = current - 1 if current > 1 else None
    adjacent_size = 2
    page_start = current - adjacent_size
    page_start = page_start if page_start > 1 else 1
    page_end = page_start + 1 + adjacent_size * 2
    adjacent_pages = range(page_start, page_end)
    adjacent = [x for x in adjacent_pages if 0 < x <= total_pages]
    return {
        'current': current,
        'total_pages': total_pages,
        'next': next_page,
        'prev': prev_page,
        'adjacent': adjacent
    }


def pictures_for_page(db, page_num, tags=None, year=None):
    offset, limit = (page_num - 1) * PAGE_SIZE, PAGE_SIZE
    if tags:
        db_pics = list(db.get_tagged_pictures(tags, limit, offset))
    elif year:
        db_pics = list(db.get_pictures_for_year(year, limit, offset))
    else:
        db_pics = list(db.get_pictures(limit, offset))
    return db_pics


def get_flickr_data(picture):
    data = picture.get('flickr')
    flickr = {'id': '', 'url': ''}
    if data:
        try:
            flickr = json.loads(data)
        except ValueError:
            # Bad Json?
            pass
    return flickr


def get_gphotos_data(picture):
    xml_data = picture.get('gphotos')
    photo_id, url = '', ''
    if xml_data:
        try:
            xml_str = json.loads(xml_data).get('xml')
        except ValueError:
            # Bad Json?
            pass
        else:
            if xml_str:
                xml = etree.parse(StringIO(xml_str))
                root = xml.getroot()
                links = root.findall('{http://www.w3.org/2005/Atom}link')
                rel = 'http://schemas.google.com/photos/2007#canonical'
                matching = [l.attrib['href'] for l in links
                            if l.attrib['rel'] == rel]
                id_node = '{http://schemas.google.com/photos/2007}id'
                photo_ids = root.findall(id_node)
                photo_id = photo_ids[0].text if photo_ids else ''
                url = matching[0] if matching else ''
    return {
        'url': url,
        'id': photo_id
    }


@app.route('/', methods=['GET'])
def index():
    db_total = db.total_pictures()
    all_tags = db.get_tags()
    years = db.get_years()
    recent = list(db.get_pictures(24, 0))
    ctx = {
        'recent': recent,
        'total': db_total,
        'all_tags': all_tags,
        'years': years
    }
    return render_template('index.html', **ctx)


@app.route('/photo/', methods=['GET'])
def photo_list():
    page = int(request.args.get('page', '1'))
    pictures = pictures_for_page(db, page)
    db_total = db.total_pictures()
    paginator = get_paginator(db_total, PAGE_SIZE, page)
    all_tags = db.get_tags()
    years = db.get_years()
    ctx = {
        'pictures': pictures,
        'total': db_total,
        'paginator': paginator,
        'all_tags': all_tags,
        'years': years
    }
    return render_template('photo_list.html', **ctx)


@app.route('/photo/<string:key>/')
def picture_detail(key):
    picture = db.get_picture(key)
    tags = db.tags_for_picture(picture['id'])
    return render_template('detail.html', **{
        'picture': picture,
        'tags': tags,
        'human_size': human_size(picture['size']),
        'flickr': get_flickr_data(picture),
        'gphotos': get_gphotos_data(picture)
    })


@app.route('/photo/<string:key>/blob/')
def picture_detail_blob(key):
    picture = db.get_picture(key)
    return render_template('detail_blob.html', **{
        'blob': json.dumps(picture, indent=2),
    })


@app.route('/tags/<string:tag_list>/')
def view_tags(tag_list):
    page = int(request.args.get('page', '1'))
    tags = [t.lower() for t in tag_list.split(',') if t]
    pictures = pictures_for_page(db, page, tags)
    tagged_total = db.total_for_tags(tags)
    paginator = get_paginator(tagged_total, PAGE_SIZE, page)
    all_tags = db.get_tags()
    ctx = {
        'selected_tags': tags,
        'all_tags': all_tags,
        'pictures': pictures,
        'paginator': paginator,
        'total': tagged_total,
    }
    return render_template('photo_list.html', **ctx)


@app.route('/date/<int:year>/')
def view_year(year):
    page = int(request.args.get('page', '1'))
    pictures = pictures_for_page(db, page, tags=None, year=year)
    tagged_total = db.total_for_year(year)
    paginator = get_paginator(tagged_total, PAGE_SIZE, page)
    all_tags = db.get_tags()
    ctx = {
        'all_tags': all_tags,
        'pictures': pictures,
        'paginator': paginator,
        'total': tagged_total,
        'year': year,
    }
    return render_template('photo_list.html', **ctx)


def serial_job(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()


@app.route('/bad_jobs/')
def bad_jobs():
    result = queue.get_bad_jobs()
    return render_template('bad_jobs.html', **{
        'bad_jobs': [(job, json.dumps(job, indent=2, default=serial_job))
                     for job in result]
    })


def start():
    log.info('Starting WEB server')
    app.run(debug=settings.DEBUG, port=5001, host='0.0.0.0')


if __name__ == "__main__":
    start()
