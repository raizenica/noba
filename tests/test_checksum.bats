#!/usr/bin/env bats

setup() {
    echo "test data" > testfile.txt
}

teardown() {
    rm -f testfile.txt testfile.txt.md5.txt
}

@test "checksum --version returns version" {
    run ./checksum.sh --version
    [ "$status" -eq 0 ]
    [[ "$output" =~ "version" ]]
}

@test "checksum generates md5 for a file" {
    run ./checksum.sh -a md5 testfile.txt
    [ "$status" -eq 0 ]
    [ -f "testfile.txt.md5.txt" ]
    grep -q "testfile.txt" "testfile.txt.md5.txt"
}
