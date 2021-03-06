#!/usr/bin/env python

# TODO
# breadth-first searching, stopping after a given level
# ensure redirects are followed

import httplib2
import sys
from BeautifulSoup import BeautifulSoup
from optparse import OptionParser
from multiprocessing import Process, Queue, current_process
from urlparse import urlsplit, urljoin, urlunsplit
import urllib
import re

script_re = re.compile(r'<script type=("|\')text/javascript("|\')>.*?</script>', re.DOTALL)

def dejsify(content):
    return script_re.sub('', content)


class Spinner:
    def __init__(self):
        self.status = 0
        self.locations = ['|', '/', '-', '\\']

    def spin(self):
        sys.stderr.write("%s\r" % self.locations[self.status])
        sys.stderr.flush()
        self.status = (self.status + 1) % 4

def worker(h, headers, input, output, constraint):
    """
    Function run by worker processes
    """
    try:
        for url in iter(input.get, 'STOP'):
            result = get_url(h, headers, url, constraint)
            output.put(result)
    except KeyboardInterrupt:
        pass

def get_url(h, headers, url, constraint):
    """
    Function used to calculate result
    """
    links = []
    try:
        resp, content = h.request(url, headers=headers)
        content = dejsify(content)
        soup = BeautifulSoup(content)
    except Exception, e:
        return (current_process().name, 'ERROR:%s' % e, url, links)
    hrefs = [a['href'] for a in soup.findAll('a') if a.has_key('href')]
    for href in hrefs:
        absolute_url = urljoin(resp.get('location', url), href.strip())
        parts = urlsplit(absolute_url)
        if parts.netloc in [constraint, ""] and parts.scheme in ["http", ""]:
            # Ignore the #foo at the end of the url
            no_fragment = parts[:4] + ("",)
            links.append(urlunsplit(no_fragment))
    return (current_process().name, resp.status, url, links)

def test(options, args):

    seen_urls = {}
    # The ones we're currently scanning
    queued_urls = {}
    # For the next level
    next_urls = {}
    depth = 0
    processes = []
    spinner = Spinner()

    # Create queues
    task_queue = Queue()
    done_queue = Queue()
    
    # check if we have to log in
    headers = {}
    h = httplib2.Http(timeout=60)
    if options.login_url:
        if options.verbose:
            print 'Logging in'
        body = {'username': options.username, 'password': options.password}
        headers = {'Content-type': 'application/x-www-form-urlencoded'}
        # check for csrf
        if options.csrf:
            response, content = h.request(options.login_url)
            soup = BeautifulSoup(content)
            token = dict(soup.find('input', attrs={'name': options.csrf}).attrs)['value']
            body[options.csrf] = token
            headers['Cookie'] = response['set-cookie']
        response, content = h.request(options.login_url, 'POST', headers=headers, body=urllib.urlencode(body))
        headers['Cookie'] = response['set-cookie']

    # Submit first url
    try:
        url = unicode(args[0])
    except IndexError:
        print "Give the spiders a URL."
        sys.exit(1)
    if not url.startswith('http://'):
        url = "http://" + url
    host = urlsplit(url).netloc
    next_urls[url] = True

    try:

        # Start worker processes
        for i in range(options.spiders):
            p = Process(target=worker, args=(h, headers, task_queue, done_queue, host))
            p.start()
            processes.append(p)

        while len(next_urls) > 0 and (depth <= options.depth or options.depth == -1):
            if options.verbose:
                print "Starting link depth %s" % depth
                sys.stdout.flush()
            for k, v in next_urls.iteritems():
                queued_urls[k] = v
                task_queue.put(k)
            next_urls = {}

            while len(queued_urls) > 0:
                name, resp_status, url, links = done_queue.get()
                if resp_status == 200:
                    if options.verbose:
                        print "[%s] %s (from %s)" % (resp_status, url, queued_urls[url])
                        sys.stdout.flush()
                    elif options.spinner:
                        spinner.spin()
                else:
                    print "[%s] %s (from %s)" % (resp_status, url, queued_urls[url])
                    sys.stdout.flush()
                del(queued_urls[url])
                seen_urls[url] = True
                for link in links:
                    if link not in seen_urls and link not in queued_urls:
                        # remember what url referenced this link
                        next_urls[link] = url
            depth += 1

    except KeyboardInterrupt:
        pass
    finally:
        # Give the spiders a chance to exit cleanly
        for i in range(options.spiders):
            task_queue.put('STOP')
        for p in processes:
            # Forcefully close the spiders
            p.terminate()
            p.join()
    print

if __name__ == '__main__':
    parser = OptionParser()
    options_a = [
        ["-s", "--spiders", dict(dest="spiders", type="int", default=1, help="sends more than one spider")],
        ["-S", "--nospinner", dict(dest="spinner", action="store_false", default=True, help="turns off the spinner")],
        ["-v", "--verbose", dict(dest="verbose", action="store_true", default=False, help="outputs every request (implies --nospiner)")],
        ["-d", "--depth", dict(dest="depth", type="int", default=-1, help="does a breadth-first crawl, stopping after DEPTH levels (implies --breadth)")],
        ["-b", "--breadth", dict(dest="breadth", action="store_true", default=False, help="does a breadth-first crawl; may be used with --depth")],
        ["-c", "--csrf", dict(dest="csrf", action="store", default=None, help="specify the name of the csrf input field")],
        ["-l", "--login-url", dict(dest="login_url", default=None, help="specify a url to log in")],
        ["-u", "--username", dict(dest="username", default=None, help="username to log in")],
        ["-p", "--password", dict(dest="password", default=None, help="password to log in")],
    ]
    for s, l, k in options_a:
        parser.add_option(s, l, **k)
    (options, args) = parser.parse_args()
    test(options, args)
