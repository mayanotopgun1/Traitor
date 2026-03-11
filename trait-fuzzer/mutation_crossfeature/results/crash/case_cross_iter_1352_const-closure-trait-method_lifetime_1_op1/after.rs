#![feature(const_trait_impl)]

const trait Tr {
    fn a(self) -> i32;
}

impl const Tr for () {
    fn a(self) -> i32 { 42 }
}

const fn need_const_closure<T: [const] FnOnce(&()) -> i32>(x: T) -> i32 {
    x(&())
}

const _: () = assert!(need_const_closure(|_: &()| Tr::a(())) == 42);

fn main() {}