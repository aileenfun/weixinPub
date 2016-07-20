#!/bin/bash
ftp -n<<!
open 192.168.1.254
user admin 541881452
binary
lcd /tmp/
cd /sda1/shareMedia/
prompt
put access_token access_token
close
bye
!