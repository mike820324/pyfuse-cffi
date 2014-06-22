from cffi import FFI
from stat import S_IFDIR, S_IFLNK, S_IFREG
from signal import signal, SIGINT, SIG_DFL
import logging

try:
    from functools import partial
except ImportError:
    # http://docs.python.org/library/functools.html#functools.partial
    def partial(func, *args, **keywords):
        def newfunc(*fargs, **fkeywords):
            newkeywords = keywords.copy()
            newkeywords.update(fkeywords)
            return func(*(args + fargs), **newkeywords)

        newfunc.func = func
        newfunc.args = args
        newfunc.keywords = keywords
        return newfunc

# the ffi instance
ffi = FFI()

# load the necessary system data structure 
with open("include/types.h", "r") as fp:
    sys_types =  fp.read()

# load the necessary data structure and function prototypes for fuse
with open("include/fuse.h", "r") as fp:
    fuse_cdef = fp.read()

std_string = """
    void *memset(void*, int, size_t);
    int strcmp(const char*, const char*);
    int strncmp(const char*, const char*, size_t);
    char *strstr(const char*, const char*);
"""

# load symbols so that python understand
ffi.cdef(sys_types + fuse_cdef + std_string)


# dynamic library or compile by cffi
# currently both methods works.
# maybe we can check the performance.
_libfuse = ffi.verify("""#include <fuse.h> #include <string.h>""", 
                libraries=['fuse'], 
                library_dir=['/lib64'], 
                define_macros=[("FUSE_USE_VERSION", "26")])

#library = ffi.dlopen("/lib64/libfuse.so")


def time_of_timespec(ts):
    return ts.tv_sec + ts.tv_nsec / 10 ** 9

def set_st_attrs(st, attrs):
    for key, val in attrs.items():
        if key in ('st_atim', 'st_mtim', 'st_ctim', 'st_birthtime'):
            timespec = getattr(st, key)
            timespec.tv_sec = int(val)
            timespec.tv_nsec = int((val - timespec.tv_sec) * 10 ** 9)
        elif hasattr(st, key):
            setattr(st, key, val)


def fuse_get_context():
    'Returns a (uid, gid, pid) tuple'

    ctxp = _libfuse.fuse_get_context()
    ctx = ctxp.contents
    return ctx.uid, ctx.gid, ctx.pid


class FuseOSError(OSError):
    def __init__(self, errno):
        super(FuseOSError, self).__init__(errno, strerror(errno))


class FUSE(object):
    '''
    This class is the lower level interface and should not be subclassed under
    normal use. Its methods are called by fuse.

    Assumes API version 2.6 or later.
    '''

    OPTIONS = (
        ('foreground', '-f'),
        ('debug', '-d'),
        ('nothreads', '-s'),
    )

    def __init__(self, operations, mountpoint, raw_fi=False, encoding='utf-8',
                 **kwargs):

        '''
        Setting raw_fi to True will cause FUSE to pass the fuse_file_info
        class as is to Operations, instead of just the fh field.

        This gives you access to direct_io, keep_cache, etc.
        '''

        self.operations = operations
        self.raw_fi = raw_fi
        self.encoding = encoding

        args = ['fuse']

        args.extend(flag for arg, flag in self.OPTIONS
                    if kwargs.pop(arg, False))

        kwargs.setdefault('fsname', operations.__class__.__name__)
        args.append('-d')
        args.append('-o')
        args.append(','.join(self._normalize_fuse_options(**kwargs)))
        args.append(mountpoint)

        args = [arg.encode(encoding) for arg in args]
        argv = [ffi.new("char[]", arg) for arg in args]


        # setup the callback function
		# the self argument will cause big problem
        methods = [x for x in dir(self) if not "_" in x]
        for method in methods:
            if hasattr(fuse_ops, method):
                cdef = ffi.typeof(getattr(fuse_ops, method)).cname
                callback = ffi.callback(cdef, getattr(self, method))
                setattr(fuse_ops, method, callback)

        try:
            old_handler = signal(SIGINT, SIG_DFL)
        except ValueError:
            old_handler = SIG_DFL

        err = _libfuse.fuse_main_real(len(args), argv, fuse_ops,
                                      ffi.sizeof(fuse_ops[0]), ffi.NULL)

        try:
            signal(SIGINT, old_handler)
        except ValueError:
            pass

        del self.operations     # Invoke the destructor
        if err:
            raise RuntimeError(err)

    @staticmethod
    def _normalize_fuse_options(**kargs):
        for key, value in kargs.items():
            if isinstance(value, bool):
                if value is True: yield key
            else:
                yield '%s=%s' % (key, value)

    @staticmethod
    def _wrapper(func, *args, **kwargs):
        'Decorator for the methods that follow'

        try:
            return func(*args, **kwargs) or 0
        except OSError, e:
            return -(e.errno or EFAULT)
        except:
            print_exc()
            return -EFAULT

    def getattr(self, path, buf):
        return self.fgetattr(path, buf, None)
    
    def readlink(self, path, buf, bufsize):
        ret = self.operations('readlink', path.decode(self.encoding)) \
                  .encode(self.encoding)

        # copies a string into the given buffer
        # (null terminated and truncated if necessary)
        data = create_string_buffer(ret[:bufsize - 1])
        memmove(buf, data, len(data))
        return 0

    def mknod(self, path, mode, dev):
        return self.operations('mknod', path.decode(self.encoding), mode, dev)

    def mkdir(self, path, mode):
        return self.operations('mkdir', path.decode(self.encoding), mode)

    def unlink(self, path):
        return self.operations('unlink', path.decode(self.encoding))

    def rmdir(self, path):
        return self.operations('rmdir', path.decode(self.encoding))

    def symlink(self, source, target):
        'creates a symlink `target -> source` (e.g. ln -s source target)'

        return self.operations('symlink', target.decode(self.encoding),
                                          source.decode(self.encoding))

    def rename(self, old, new):
        return self.operations('rename', old.decode(self.encoding),
                                         new.decode(self.encoding))

    def link(self, source, target):
        'creates a hard link `target -> source` (e.g. ln source target)'

        return self.operations('link', target.decode(self.encoding),
                                       source.decode(self.encoding))

    def chmod(self, path, mode):
        return self.operations('chmod', path.decode(self.encoding), mode)

    def chown(self, path, uid, gid):
        # Check if any of the arguments is a -1 that has overflowed
        if c_uid_t(uid + 1).value == 0:
            uid = -1
        if c_gid_t(gid + 1).value == 0:
            gid = -1

        return self.operations('chown', path.decode(self.encoding), uid, gid)

    def truncate(self, path, length):
        return self.operations('truncate', path.decode(self.encoding), length)

    def open(self, path, fip):
        fi = fip.contents
        if self.raw_fi:
            return self.operations('open', path.decode(self.encoding), fi)
        else:
            fi.fh = self.operations('open', path.decode(self.encoding),
                                            fi.flags)

            return 0

    def read(self, path, buf, size, offset, fip):
        if self.raw_fi:
          fh = fip.contents
        else:
          fh = fip.contents.fh

        ret = self.operations('read', path.decode(self.encoding), size,
                                      offset, fh)

        if not ret: return 0

        retsize = len(ret)
        assert retsize <= size, \
            'actual amount read %d greater than expected %d' % (retsize, size)

        data = create_string_buffer(ret, retsize)
        memmove(buf, ret, retsize)
        return retsize

    def _write(self, path, buf, size, offset, fip):
        data = string_at(buf, size)

        if self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        return self.operations('write', path.decode(self.encoding), data,
                                        offset, fh)

    def statfs(self, path, buf):
        stv = buf.contents
        attrs = self.operations('statfs', path.decode(self.encoding))
        for key, val in attrs.items():
            if hasattr(stv, key):
                setattr(stv, key, val)

        return 0

    def flush(self, path, fip):
        if self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        return self.operations('flush', path.decode(self.encoding), fh)

    def release(self, path, fip):
        if self.raw_fi:
          fh = fip.contents
        else:
          fh = fip.contents.fh

        return self.operations('release', path.decode(self.encoding), fh)

    def fsync(self, path, datasync, fip):
        if self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        return self.operations('fsync', path.decode(self.encoding), datasync,
                                        fh)

    def _setxattr(self, path, name, value, size, options, *args):
        return self.operations('setxattr', path.decode(self.encoding),
                               name.decode(self.encoding),
                               string_at(value, size), options, *args)

    def getxattr(self, path, name, value, size, *args):
        ret = self.operations('getxattr', path.decode(self.encoding),
                                          name.decode(self.encoding), *args)

        retsize = len(ret)
        # allow size queries
        if not value: return retsize

        # do not truncate
        if retsize > size: return -ERANGE

        buf = create_string_buffer(ret, retsize)    # Does not add trailing 0
        memmove(value, buf, retsize)

        return retsize

    def listxattr(self, path, namebuf, size):
        attrs = self.operations('listxattr', path.decode(self.encoding)) or ''
        ret = '\x00'.join(attrs).encode(self.encoding) + '\x00'

        retsize = len(ret)
        # allow size queries
        if not namebuf: return retsize

        # do not truncate
        if retsize > size: return -ERANGE

        buf = create_string_buffer(ret, retsize)
        memmove(namebuf, buf, retsize)

        return retsize

    def removexattr(self, path, name):
        return self.operations('removexattr', path.decode(self.encoding),
                                              name.decode(self.encoding))

    def opendir(self, path, fip):
        # Ignore raw_fi
        fip.contents.fh = self.operations('opendir',
                                          path.decode(self.encoding))

        return 0

    def readdir(self, path, buf, filler, offset, fip):
        # Ignore raw_fi
        for item in self.operations('readdir', path.decode(self.encoding),
                                               fip.contents.fh):

            if isinstance(item, basestring):
                name, st, offset = item, None, 0
            else:
                name, attrs, offset = item
                if attrs:
                    st = c_stat()
                    set_st_attrs(st, attrs)
                else:
                    st = None

            if filler(buf, name.encode(self.encoding), st, offset) != 0:
                break

        return 0

    def releasedir(self, path, fip):
        # Ignore raw_fi
        return self.operations('releasedir', path.decode(self.encoding),
                                             fip.contents.fh)

    def fsyncdir(self, path, datasync, fip):
        # Ignore raw_fi
        return self.operations('fsyncdir', path.decode(self.encoding),
                                           datasync, fip.contents.fh)

    def init(self, conn):
        return self.operations('init', '/')

    def destroy(self, private_data):
        return self.operations('destroy', '/')
    
    def access(self, path, amode):
        return self.operations('access', path.decode(self.encoding), amode)

    def create(self, path, mode, fip):
        fi = fip.contents
        path = path.decode(self.encoding)

        if self.raw_fi:
            return self.operations('create', path, mode, fi)
        else:
            fi.fh = self.operations('create', path, mode)
            return 0
    
    def ftruncate(self, path, length, fip):
        if self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        return self.operations('truncate', path.decode(self.encoding),
                                           length, fh)

    def fgetattr(self, path, buf, fip):
        memset(buf, 0, sizeof(c_stat))

        st = buf.contents
        if not fip:
            fh = fip
        elif self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        attrs = self.operations('getattr', path.decode(self.encoding), fh)
        set_st_attrs(st, attrs)
        return 0

    def lock(self, path, fip, cmd, lock):
        if self.raw_fi:
            fh = fip.contents
        else:
            fh = fip.contents.fh

        return self.operations('lock', path.decode(self.encoding), fh, cmd,
                                       lock)

    def _utimens(self, path, buf):
        if buf:
            atime = time_of_timespec(buf.actime)
            mtime = time_of_timespec(buf.modtime)
            times = (atime, mtime)
        else:
            times = None

        return self.operations('utimens', path.decode(self.encoding), times)

    def bmap(self, path, blocksize, idx):
        return self.operations('bmap', path.decode(self.encoding), blocksize,
                                       idx)


class Operations(object):
    '''
    This class should be subclassed and passed as an argument to FUSE on
    initialization. All operations should raise a FuseOSError exception on
    error.

    When in doubt of what an operation should do, check the FUSE header file
    or the corresponding system call man page.
    '''

    def __call__(self, op, *args):
        if not hasattr(self, op):
            raise FuseOSError(EFAULT)
        return getattr(self, op)(*args)

    def access(self, path, amode):
        return 0

    bmap = None

    def chmod(self, path, mode):
        raise FuseOSError(EROFS)

    def chown(self, path, uid, gid):
        raise FuseOSError(EROFS)

    def create(self, path, mode, fi=None):
        '''
        When raw_fi is False (default case), fi is None and create should
        return a numerical file handle.

        When raw_fi is True the file handle should be set directly by create
        and return 0.
        '''

        raise FuseOSError(EROFS)

    def destroy(self, path):
        'Called on filesystem destruction. Path is always /'

        pass

    def flush(self, path, fh):
        return 0

    def fsync(self, path, datasync, fh):
        return 0

    def fsyncdir(self, path, datasync, fh):
        return 0

    def getattr(self, path, fh=None):
        '''
        Returns a dictionary with keys identical to the stat C structure of
        stat(2).

        st_atim, st_mtim and st_ctim should be floats.

        NOTE: There is an incombatibility between Linux and Mac OS X
        concerning st_nlink of directories. Mac OS X counts all files inside
        the directory, while Linux counts only the subdirectories.
        '''

        if path != '/':
            raise FuseOSError(ENOENT)
        return dict(st_mode=(S_IFDIR | 0755), st_nlink=2)

    def getxattr(self, path, name, position=0):
        raise FuseOSError(ENOTSUP)

    def init(self, path):
        '''
        Called on filesystem initialization. (Path is always /)

        Use it instead of __init__ if you start threads on initialization.
        '''

        pass

    def link(self, target, source):
        'creates a hard link `target -> source` (e.g. ln source target)'

        raise FuseOSError(EROFS)

    def listxattr(self, path):
        return []

    lock = None

    def mkdir(self, path, mode):
        raise FuseOSError(EROFS)

    def mknod(self, path, mode, dev):
        raise FuseOSError(EROFS)

    def open(self, path, flags):
        '''
        When raw_fi is False (default case), open should return a numerical
        file handle.

        When raw_fi is True the signature of open becomes:
            open(self, path, fi)

        and the file handle should be set directly.
        '''

        return 0

    def opendir(self, path):
        'Returns a numerical file handle.'

        return 0

    def read(self, path, size, offset, fh):
        'Returns a string containing the data requested.'

        raise FuseOSError(EIO)

    def readdir(self, path, fh):
        '''
        Can return either a list of names, or a list of (name, attrs, offset)
        tuples. attrs is a dict as in getattr.
        '''

        return ['.', '..']

    def readlink(self, path):
        raise FuseOSError(ENOENT)

    def release(self, path, fh):
        return 0

    def releasedir(self, path, fh):
        return 0

    def removexattr(self, path, name):
        raise FuseOSError(ENOTSUP)

    def rename(self, old, new):
        raise FuseOSError(EROFS)

    def rmdir(self, path):
        raise FuseOSError(EROFS)

    def setxattr(self, path, name, value, options, position=0):
        raise FuseOSError(ENOTSUP)

    def statfs(self, path):
        '''
        Returns a dictionary with keys identical to the statvfs C structure of
        statvfs(3).

        On Mac OS X f_bsize and f_frsize must be a power of 2
        (minimum 512).
        '''

        return {}

    def symlink(self, target, source):
        'creates a symlink `target -> source` (e.g. ln -s source target)'

        raise FuseOSError(EROFS)

    def truncate(self, path, length, fh=None):
        raise FuseOSError(EROFS)

    def unlink(self, path):
        raise FuseOSError(EROFS)

    def utimens(self, path, times=None):
        'Times is a (atime, mtime) tuple. If None use current time.'

        return 0

    def write(self, path, data, offset, fh):
        raise FuseOSError(EROFS)


class LoggingMixIn:
    log = logging.getLogger('fuse.log-mixin')

    def __call__(self, op, path, *args):
        self.log.debug('-> %s %s %s', op, path, repr(args))
        ret = '[Unhandled Exception]'
        try:
            ret = getattr(self, op)(path, *args)
            return ret
        except OSError, e:
            ret = str(e)
            raise
        finally:
            self.log.debug('<- %s %s', op, repr(ret))

