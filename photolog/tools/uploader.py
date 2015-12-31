import os
import yaml
import requests
import argparse
from time import time
from hashlib import md5
from urllib.parse import urljoin
from photolog.services.base import file_checksum
from photolog import cli_logger as log, ALLOWED_FILES, IMAGE_FILES, RAW_FILES

BATCH_SIZE = 1999  # Max Gphotos album is 2000
UPLOAD_ATTEMPTS = 3


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def read_local_conf(conf_file=None):
    if not conf_file:
        home = os.path.expanduser('~')
        conf_file = os.path.join(home, '.photolog')
    log.info('Reading config file: %s' % conf_file)
    conf = yaml.load(open(conf_file))
    return conf


def start_batch(endpoint, secret):
    batch_endpoint = urljoin(endpoint, 'batch/')
    response = requests.post(batch_endpoint, headers={
        'X-PHOTOLOG-SECRET': secret
    })
    batch_id = response.json()['batch_id']
    return batch_id


def verify_exists(host, full_filepath, secret):
    verification = urljoin(host, '/photos/verify/')
    checksum = file_checksum(full_filepath)
    filename = os.path.basename(full_filepath)
    response = requests.get(verification, params={
        'filename': filename,
        'checksum': checksum
    }, headers={
        'X-PHOTOLOG-SECRET': secret
    })
    return response.status_code == 204


def handle_file(host, full_file, secret, tags, skip, halt):
    """
    :param host: Host to upload data to
    :param full_file: Full file path in local machine
    :param secret: API secret
    :param tags: Tags to use for file
    :param skip: Steps for job to skip
    :param halt: If True, will wait for user input to resume after attempts
    :return: Returns if the file was uploaded or not
    """

    answer = 'Y'
    while answer == 'Y':
        attempt = 1
        while attempt < UPLOAD_ATTEMPTS:
            try:
                file_exists = verify_exists(host, full_file, secret)
                endpoint = urljoin(host, '/photos/')
                if file_exists:
                    log.info('File %s already uploaded' % full_file)
                    return False
                else:
                    requests.post(endpoint, data={
                        'tags': tags,
                        'skip': skip,
                        # 'batch_id': None,
                        # 'is_last': False,  # n == total_files
                    }, files={
                        'photo_file': open(full_file, 'rb'),
                    }, headers={
                        'X-PHOTOLOG-SECRET': secret
                    })
                    return True
            except requests.ConnectionError:
                attempt += 1
                log.warning("Attempt %s. Failed to connect. Retrying" % attempt)

        if halt:
            answer = input("Problem connecting, Continue? [Y, n]") or 'Y'
        else:
            answer = 'n'
    raise requests.ConnectionError('Could not connect to %s' % host)


def upload_directories(targets, host, secret, tags, skip, halt):
    start = time()
    first_batch, second_batch = [], []
    for target in targets:
        if os.path.isdir(target):
            for file in os.listdir(target):
                name, ext = os.path.splitext(file)
                ext = ext.lstrip('.').lower()
                if ext not in ALLOWED_FILES:
                    continue
                full_file = os.path.join(target, file)
                if ext in IMAGE_FILES:
                    first_batch.append((file, full_file))
                elif ext in RAW_FILES:
                    second_batch.append((file, full_file))
        else:
            name, ext = os.path.splitext(target)
            ext = ext.lstrip('.').lower()
            full_file = os.path.abspath(target)
            if ext not in ALLOWED_FILES:
                continue
            if ext in IMAGE_FILES:
                first_batch.append((target, full_file))
            elif ext in RAW_FILES:
                second_batch.append((target, full_file))

    n, skipped = 1, 0
    total_files = len(first_batch) + len(second_batch)
    log.info('Found %s files' % total_files)
    for batch in chunks(sorted(first_batch) + sorted(second_batch), BATCH_SIZE):
        #batch_id = start_batch(endpoint, secret)
        for file, full_file in batch:
            log.info('Uploading %s [%s/%s]' % (full_file, n, total_files))
            file_start = time()
            uploaded = handle_file(host, full_file, secret, tags, skip, halt)
            skipped += 1 if not uploaded else 0
            pct = 100 * n / total_files
            log.info("Done in %0.2fs [%0.1f%%]" % (time() - file_start, pct))
            n += 1
    elapsed = time() - start
    log.info('Skipped files: %s' % skipped)
    log.info('Uploaded %s files in %.2fs' % (total_files, elapsed))


def run():
    config = read_local_conf()
    parser = argparse.ArgumentParser(
        description="Upload files or directories to Photolog"
    )
    parser.add_argument('directories', type=str, nargs='+',
        help="Directory to upload")
    parser.add_argument('--tags', metavar='T', nargs='?', type=str,
        help="Tags for this batch")
    parser.add_argument('--host', metavar='H', nargs='?', type=str,
        help="Host to upload")
    parser.add_argument('--skip', nargs='?', type=str,
        help="steps to skip")
    parsed = parser.parse_args()
    directories = [os.path.realpath(d) for d in parsed.directories]
    halt = config.get('halt', False)
    host = parsed.host or config['host']
    secret = md5(config['secret'].encode('utf-8')).hexdigest()
    tags = parsed.tags or ''
    skip = parsed.skip or ''
    upload_directories(directories, host, secret, tags, skip, halt)


if __name__ == '__main__':
    run()
