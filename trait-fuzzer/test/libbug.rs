#![crate_type = "sdylib"]
#![allow(incomplete_features, improper_ctypes_definitions)]
#![feature(export_stable)]
#![feature(inherent_associated_types)]
mod m {
    #[export_stable]
    pub struct S;
    pub fn foo() -> i32;
}
#[export_stable]
pub use m::foo;
#[export_stable]
pub mod m1 {
    #[repr(C)]
    pub struct S1;
    struct S2;
    pub struct S3;
}
pub mod fn_sig {
    #[export_stable]
    pub fn foo1();
    #[export_stable]
    #[repr(C)]
    pub struct S;
    #[export_stable]
    pub extern "C" fn foo2(x: S) -> i32;
    #[export_stable]
    pub extern "C" fn foo3(x: Box<S>) -> u32;
}
pub mod impl_item {
    pub struct S;
    impl S {
        #[export_stable]
        pub extern "C" fn foo1(&self) -> i32;
        #[export_stable]
        pub extern "C" fn foo2(self) -> i32;
    }
    pub struct S2<T>(T);
    impl<T> S2<T> {
        #[export_stable]
        pub extern "C" fn foo1(&self);
    }
}
pub mod tys {
    pub trait Trait {
        type Type;
    }
    pub struct S;
    impl<T> S2<T> {
        #[export_stable]
        pub extern "C" fn foo1(_x: Type);
    }
    #[export_stable]
    pub extern "C" fn foo1(x: <S as Trait>::Type) -> u32;
    #[export_stable]
    pub type Type = [i32; 4];
    #[export_stable]
    pub extern "C" fn foo2(_x: Type);
    impl S {
        #[export_stable]
        pub type Type = extern "C" fn();
    }
    #[export_stable]
    pub extern "C" fn foo3(_x: S::Type);
    #[export_stable]
    pub extern "C" fn foo4() -> impl Copy;
}
pub mod privacy {
    #[export_stable]
    #[repr(C)]
    pub struct S1 {
        pub x: i32,
    }
    #[export_stable]
    #[repr(C)]
    pub struct S2 {
        x: i32,
    }
    #[export_stable]
    #[repr(i32)]
    enum E {
        Variant1 {
            x: i32,
        },
    }
}
pub mod use_site {
    #[export_stable]
    pub trait Trait { }
    #[export_stable]
    pub const C: i32 = 0;
}
fn main();
