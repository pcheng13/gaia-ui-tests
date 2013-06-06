# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import cgi
import datetime
import json
import os
import sys
import textwrap
import time
import base64

from py.xml import html
from py.xml import raw
from marionette import MarionetteTestOptions
from marionette import MarionetteTestResult
from marionette import MarionetteTestRunner
from marionette import MarionetteTextTestRunner
from marionette.runtests import cli

from gaiatest import GaiaTestCase


class GaiaTestResult(MarionetteTestResult):

    def addError(self, test, err):
        self.errors.append((test, self._exc_info_to_string(err, test), self.gather_debug()))

    def addFailure(self, test, err):
        self.failures.append((test, self._exc_info_to_string(err, test), self.gather_debug()))

    def gather_debug(self):
        debug = {}
        try:
            debug['screenshot'] = self.marionette.screenshot()[22:]
            debug['source'] = self.marionette.page_source
            self.marionette.switch_to_frame()
            debug['settings'] = json.dumps(self.marionette.execute_async_script("""
SpecialPowers.addPermission('settings-read', true, document);
var req = window.navigator.mozSettings.createLock().get('*');
req.onsuccess = function() {
  marionetteScriptFinished(req.result);
}""", special_powers=True))
        except:
            pass
        return debug


class GaiaTestOptions(MarionetteTestOptions):

    def __init__(self, **kwargs):
        MarionetteTestOptions.__init__(self, **kwargs)
        group = self.add_option_group('gaiatest')
        group.add_option('--restart',
                         action='store_true',
                         dest='restart',
                         default=False,
                         help='restart target instance between tests')
        group.add_option('--html-output',
                         action='store',
                         dest='html_output',
                         help='html output')


class GaiaTestRunner(MarionetteTestRunner):

    def __init__(self, html_output=None, **kwargs):
        MarionetteTestRunner.__init__(self, **kwargs)
        self.textrunnerclass = GaiaTextTestRunner

        width = 80
        if not (self.testvars.get('acknowledged_risks') is True or os.environ.get('GAIATEST_ACKNOWLEDGED_RISKS')):
            url = 'https://developer.mozilla.org/en-US/docs/Gaia_Test_Runner#Risks'
            heading = 'Acknowledge risks'
            message = 'These tests are destructive and will remove data from the target Firefox OS instance as well ' \
                      'as using services that may incur costs! Before you can run these tests you must follow the ' \
                      'steps to indicate you have acknowledged the risks detailed at the following address:'
            print '\n' + '*' * 5 + ' %s ' % heading.upper() + '*' * (width - len(heading) - 7)
            print '\n'.join(textwrap.wrap(message, width))
            print url
            print '*' * width + '\n'
            sys.exit(1)
        if not (self.testvars.get('skip_warning') is True or os.environ.get('GAIATEST_SKIP_WARNING')):
            delay = 30
            heading = 'Warning'
            message = 'You are about to run destructive tests against a Firefox OS instance. These tests ' \
                      'will restore the target to a clean state, meaning any personal data such as contacts, ' \
                      'messages, photos, videos, music, etc. will be removed. The tests may also attempt to ' \
                      'initiate outgoing calls, or connect to services such as cellular data, wifi, gps, ' \
                      'bluetooth, etc.'
            try:
                print '\n' + '*' * 5 + ' %s ' % heading.upper() + '*' * (width - len(heading) - 7)
                print '\n'.join(textwrap.wrap(message, width))
                print '*' * width + '\n'
                print 'To abort the test run hit Ctrl+C on your keyboard.'
                print 'The test run will continue in %d seconds.' % delay
                time.sleep(delay)
            except KeyboardInterrupt:
                print '\nTest run aborted by user.'
                sys.exit(1)
            print 'Continuing with test run...\n'

        # for HTML output
        self.html_output = html_output
        self.testvars['html_output'] = self.html_output
        self.results = []

    def register_handlers(self):
        self.test_handlers.extend([GaiaTestCase])

    def run_tests(self, tests):
        MarionetteTestRunner.run_tests(self, tests)

        if self.html_output:
            # change default encoding to avoid encoding problem for page source
            reload(sys)
            sys.setdefaultencoding('utf-8')
            html_dir = os.path.dirname(os.path.abspath(self.html_output))
            if not os.path.exists(html_dir):
                os.makedirs(html_dir)
            with open(self.html_output, 'w') as f:
                f.write(self.generate_html(self.results))

    def generate_html(self, results_list):

        def failed_count(results):
            count = len(results.failures)
            if hasattr(results, 'unexpectedSuccesses'):
                count += len(results.unexpectedSuccesses)
            return count

        tests = sum([results.testsRun for results in results_list])
        failures = sum([failed_count(results) for results in results_list])
        skips = sum([len(results.skipped) + len(results.expectedFailures) for results in results_list])
        errors = sum([len(results.errors) for results in results_list])
        passes = 0
        test_time = self.elapsedtime.total_seconds()
        test_logs = []

        def _extract_html(test, text='', result='passed', debug=None):
            cls_name = test.__class__.__name__
            tc_name = unicode(test).split()[0]
            tc_time = str(test.duration)
            additional_html = []
            links_html = []

            if result in ['failure', 'error', 'skipped']:
                if debug and debug.get('screenshot'):
                    screenshot = 'data:image/png;base64,%s' % debug['screenshot']
                    additional_html.append(
                        html.div(
                            html.a(html.img(src=screenshot), href=screenshot), class_='screenshot'))
                for name, content in debug.items():
                    try:
                        if 'screenshot' in name:
                            links_html.append(html.a(name, href='data:image/png;base64,%s' % content.encode('us-ascii')))
                        else:
                            # use base64 to avoid that some browser(such as Firefox, Opera) treats '#' as the start of another link if the data URL contains.
                            # use 'charset=utf-8' to show special characters like Chinese.
                            links_html.append(html.a(name, href='data:text/plain;charset=utf-8;base64,%s' % base64.b64encode(content)))
                        links_html.append(' ')
                    except:
                        pass

                log = html.div(class_=result)
                for line in text.splitlines():
                    separator = line.startswith(' ' * 10)
                    if separator:
                        log.append(line[:80])
                    else:
                        if line.lower().find("error") != -1 or line.lower().find("exception") != -1:
                            log.append(html.span(raw(cgi.escape(line)), class_='error'))
                        else:
                            log.append(raw(cgi.escape(line)))
                    log.append(html.br())
                additional_html.append(log)

            test_logs.append(html.tr([
                html.td(result, class_='col-result'),
                html.td(cls_name, class_='col-class'),
                html.td(tc_name, class_='col-name'),
                html.td(tc_time, class_='col-duration'),
                html.td(links_html, class_='col-links'),
                html.td(additional_html, class_='debug')],
                class_=result.lower() + ' results-table-row'))

        for results in results_list:
            for test in results.tests_passed:
                _extract_html(test)
                passes = passes + 1
            for result in results.failures:
                _extract_html(result[0], text=result[1], result='failure', debug=result[2])
            for result in results.errors:
                _extract_html(result[0], text=result[1], result='error', debug=result[2])

            jquery_src = os.path.abspath(os.path.join(os.path.dirname(__file__), 'resources', 'jquery.js'))
            main_src = os.path.abspath(os.path.join(os.path.dirname(__file__), 'resources', 'main.js'))
            style_src = os.path.abspath(os.path.join(os.path.dirname(__file__), 'resources', 'style.css'))

        generated = datetime.datetime.now()
        doc = html.html(
            html.head(
                html.meta(charset='utf-8'),
                html.title('Test Report'),
                html.link(rel='stylesheet', href=style_src),
                html.script(src=jquery_src),
                html.script(src=main_src)),
            html.body(
                html.p('Report generated on %s at %s' % (
                    generated.strftime('%d-%b-%Y'),
                    generated.strftime('%H:%M:%S'))),
                html.table(
                    html.h2('Summary'),
                    html.p('%i tests ran. in %i seconds' % (tests, test_time),
                           html.br(),
                           html.span('%i passed' % passes, class_='passed'), ', ',
                           html.span('%i failed' % failures, class_='failed'), ', ',
                           html.span('%i skipped' % skips, class_='skipped'), ', ',
                           html.span('%i error' % errors, class_='error'),
                           html.br()),
                    html.h2('Results'),
                    html.table([html.thead(
                        html.tr([
                            html.th('Result', class_='sortable', col='result'),
                            html.th('Class', class_='sortable', col='class'),
                            html.th('Test Name', class_='sortable', col='name'),
                            html.th('Duration', class_='sortable numeric', col='duration'),
                            html.th('Links')]), id='results-table-head'),
                        html.tbody(test_logs, id='results-table-body')], id='results-table')
                )
            )
        )
        return doc.unicode(indent=2)


class GaiaTextTestRunner(MarionetteTextTestRunner):

    resultclass = GaiaTestResult


def main():
    cli(runner_class=GaiaTestRunner, parser_class=GaiaTestOptions)

if __name__ == "__main__":
    main()
