from __future__ import absolute_import, unicode_literals

import celery
import djcelery
import django
import sys

from django.core.management.base import BaseCommand

from djcelery.compat import setenv

DB_SHARED_THREAD = """\
DatabaseWrapper objects created in a thread can only \
be used in that same thread.  The object with alias '{0}' \
was created in thread id {1} and this is thread id {2}.\
"""

VALIDATE_MODELS = not django.VERSION >= (1, 7)


def patch_thread_ident():
    # monkey patch django.
    # This patch make sure that we use real threads to get the ident which
    # is going to happen if we are using gevent or eventlet.
    # -- patch taken from gunicorn
    if getattr(patch_thread_ident, 'called', False):
        return
    try:
        from django.db.backends import BaseDatabaseWrapper, DatabaseError

        if 'validate_thread_sharing' in BaseDatabaseWrapper.__dict__:
            import thread
            _get_ident = thread.get_ident

            __old__init__ = BaseDatabaseWrapper.__init__

            def _init(self, *args, **kwargs):
                __old__init__(self, *args, **kwargs)
                self._thread_ident = _get_ident()

            def _validate_thread_sharing(self):
                if (not self.allow_thread_sharing
                        and self._thread_ident != _get_ident()):
                    raise DatabaseError(
                        DB_SHARED_THREAD % (
                            self.alias, self._thread_ident, _get_ident()),
                    )

            BaseDatabaseWrapper.__init__ = _init
            BaseDatabaseWrapper.validate_thread_sharing = \
                _validate_thread_sharing

        patch_thread_ident.called = True
    except ImportError:
        pass
patch_thread_ident()


class CeleryCommand(BaseCommand):
    options = BaseCommand.option_list
    skip_opts = ['--app', '--loader', '--config', '--no-color']
    requires_model_validation = VALIDATE_MODELS
    keep_base_opts = False
    stdout, stderr = sys.stdout, sys.stderr

    def get_version(self):
        return 'celery {c.__version__}\ndjango-celery {d.__version__}'.format(
            c=celery, d=djcelery,
        )

    def execute(self, *args, **options):
        broker = options.get('broker')
        if broker:
            self.set_broker(broker)
        super(CeleryCommand, self).execute(*args, **options)

    def set_broker(self, broker):
        setenv('CELERY_BROKER_URL', broker)

    def run_from_argv(self, argv):
        self.handle_default_options(argv[2:])
        return super(CeleryCommand, self).run_from_argv(argv)

    def handle_default_options(self, argv):
        acc = []
        broker = None
        for i, arg in enumerate(argv):
            # --settings and --pythonpath are also handled
            # by BaseCommand.handle_default_options, but that is
            # called with the resulting options parsed by optparse.
            if '--settings=' in arg:
                _, settings_module = arg.split('=')
                setenv('DJANGO_SETTINGS_MODULE', settings_module)
            elif '--pythonpath=' in arg:
                _, pythonpath = arg.split('=')
                sys.path.insert(0, pythonpath)
            elif '--broker=' in arg:
                _, broker = arg.split('=')
            elif arg == '-b':
                broker = argv[i + 1]
            else:
                acc.append(arg)
        if broker:
            self.set_broker(broker)
        return argv if self.keep_base_opts else acc

    def die(self, msg):
        sys.stderr.write(msg)
        sys.stderr.write('\n')
        sys.exit()

    def _is_unwanted_option(self, option):
        return option._long_opts and option._long_opts[0] in self.skip_opts

    @property
    def option_list(self):
        return [x for x in self.options if not self._is_unwanted_option(x)]
