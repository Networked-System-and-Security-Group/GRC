CC = gcc
# -DBFRT_GENERIC_FLAGS 是 SDE 9.7.1 下 bf_rt 的通用 flags 变体（entry_get/mod/add 带 flags 参数）
CFLAGS = -O2 -g -DBFRT_GENERIC_FLAGS -Wall -I. -I$(SDE_INSTALL)/include
LDFLAGS = -L$(SDE_INSTALL)/lib
LIBS = -ldriver -lbf_switchd_lib -lpthread -lm

ctrl: ctrl.c headers.h ../config.h
	@test -n "$(SDE_INSTALL)" || { echo "Set SDE_INSTALL to your SDK install directory" >&2; exit 1; }
	$(CC) $(CFLAGS) -o $@ ctrl.c $(LDFLAGS) $(LIBS)

clean:
	rm -f ctrl

.PHONY: clean
