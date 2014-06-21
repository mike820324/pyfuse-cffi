
/* platform specific */
typedef unsigned long int __dev_t;
typedef unsigned int __uid_t;
typedef unsigned int __gid_t;
typedef unsigned long int __ino_t;
typedef unsigned int __mode_t;
typedef unsigned long int __nlink_t;
typedef long int __off_t;
typedef long int __off64_t;
typedef int __pid_t;
typedef long int __blksize_t;
typedef long int __blkcnt_t;
typedef unsigned long int __fsblkcnt64_t;
typedef unsigned long int __fsfilcnt64_t;


typedef __dev_t dev_t;
typedef __gid_t gid_t;
typedef __uid_t uid_t;
typedef __pid_t pid_t;
typedef __mode_t mode_t;
typedef __off64_t off_t;

struct stat
{
    __dev_t st_dev;
    __ino_t st_ino;
    __nlink_t st_nlink;
    __mode_t st_mode;
    __uid_t st_uid;
    __gid_t st_gid;
    int __pad0;
    __dev_t st_rdev;
    __off_t st_size;
    __blksize_t st_blksize;
    __blkcnt_t st_blocks;
    struct timespec st_atim;
    struct timespec st_mtim;
    struct timespec st_ctim;
    long int __unused[3];
};

struct statvfs
  {
    unsigned long int f_bsize;
    unsigned long int f_frsize;
    __fsblkcnt64_t f_blocks;
    __fsblkcnt64_t f_bfree;
    __fsblkcnt64_t f_bavail;
    __fsfilcnt64_t f_files;
    __fsfilcnt64_t f_ffree;
    __fsfilcnt64_t f_favail;

    unsigned long int f_fsid;



    unsigned long int f_flag;
    unsigned long int f_namemax;
    int __f_spare[6];
  };
struct timespec
{
    long int tv_sec;
    long int tv_nsec;
};
