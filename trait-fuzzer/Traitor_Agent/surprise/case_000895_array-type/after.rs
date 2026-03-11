#![allow(dead_code)]
#![feature(repr_simd, core_intrinsics)]

use std::intrinsics::simd::{simd_extract, simd_insert};

#[repr(simd)]
#[derive(Copy, Clone)]
struct S([i32; 4]);

#[repr(simd)]
#[derive(Copy, Clone)]
struct T<const N: usize>([i32; N]);

trait SimdInsert {
    type Value;
    unsafe fn insert(self, index: u8, value: Self::Value) -> Self;
}

trait SimdExtract {
    type Value;
    unsafe fn extract(self, index: u8) -> Self::Value;
}

impl SimdInsert for S {
    type Value = i32;
    unsafe fn insert(mut self, index: u8, value: Self::Value) -> Self {
        self.0[index as usize] = value;
        self
    }
}

impl SimdExtract for S {
    type Value = i32;
    unsafe fn extract(self, index: u8) -> Self::Value {
        self.0[index as usize]
    }
}

impl<const N: usize> SimdInsert for T<N> {
    type Value = i32;
    unsafe fn insert(mut self, index: u8, value: Self::Value) -> Self {
        self.0[index as usize] = value;
        self
    }
}

impl<const N: usize> SimdExtract for T<N> {
    type Value = i32;
    unsafe fn extract(self, index: u8) -> Self::Value {
        self.0[index as usize]
    }
}

fn main() {
    let mut s = S([1, 2, 3, 4]);
    unsafe {
        let updated_s = s.insert(2, 10);
        assert_eq!(updated_s.0[2], 10);
        let value = s.extract(2);
        assert_eq!(value, 3);
    }

    let mut t = T([5, 6, 7, 8]);
    unsafe {
        let updated_t = t.insert(2, 20);
        assert_eq!(updated_t.0[2], 20);
        let value = t.extract(2);
        assert_eq!(value, 7);
    }
}