from cffi import FFI

from stat import S_IFDIR, S_IFLNK, S_IFREG
from time import time

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
library = ffi.verify("""#include <fuse.h> #include <string.h>""", 
				libraries=['fuse'], 
				library_dir=['/lib64'], 
				define_macros=[("FUSE_USE_VERSION", "26")])

#library = ffi.dlopen("/lib64/libfuse.so")


############### DEBUG PURPOSE CODE #############################
def set_st_attrs(st, attrs):
		for key, val in attrs.items():
				if key in ('st_atim', 'st_mtim', 'st_ctim', 'st_birthtim'):
						timespec = getattr(st, key)
						timespec.tv_sec = int(val)
						timespec.tv_nsec = int((val - timespec.tv_sec)*10 **9)
				elif hasattr(st, key):
						setattr(st, key, val)

now = time()
files = dict()
# current only one file
files['/'] = dict(st_mode=(S_IFDIR | 0755), 
				st_ctim=now, st_mtim=now, 
				st_atim=now, st_nlink = 2)

files['/hello'] = dict(st_mode = (S_IFREG | 0644),
				st_ctim=now, st_mtim=now,
				st_atim=now, st_nlink = 1,
				st_size = 20)

@ffi.callback("int(const char*, void*, fuse_fill_dir_t, off_t, struct fuse_file_info *)")
def example_readdir(path, buf, filler, offset, fip):
		fake_items = ['.', '..', 'hello']
		for item in fake_items:
				if isinstance(item, basestring):
						name, st, offset = item, ffi.NULL, 0
				if filler(buf, name, st, offset) != 0:
						break
		return 0


@ffi.callback("int(const char*, struct stat*)")
def example_getattr(path, stbuf):
		library.memset(stbuf, 0, ffi.sizeof("struct stat"))
		for key, val in files.items():
				if library.strcmp(path, key) == 0:
						set_st_attrs(stbuf, val)
		return 0



# create a fuse_operations object
test = ffi.new("struct fuse_operations *")
test.readdir = example_readdir
test.getattr = example_getattr

# this is a fake one, do not use it
# the following code is just for debug purpose
# add -d option for debug purpose
library.fuse_main_real(3, [ffi.new("char[]", "./a.out"), ffi.new("char[]","./fusetest"), ffi.new("char[]", "-d")], 
				test, ffi.sizeof("struct fuse_operations"), ffi.NULL)

