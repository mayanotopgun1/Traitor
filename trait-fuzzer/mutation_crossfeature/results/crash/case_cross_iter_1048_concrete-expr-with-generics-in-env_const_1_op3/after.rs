#![expect(incomplete_features)]
#![feature(min_generic_const_args, generic_const_items)]

pub trait Tr<const X: usize> {
    #[type_const]
    const N1<T>: usize;
    #[type_const]
    const N2<const I: usize>: usize;
    #[type_const]
    const N3: usize;
    #[type_const]
    const NEW_CONST: usize; // Added associated constant
}

pub struct S;

impl<const X: usize> Tr<X> for S {
    #[type_const]
    const N1<T>: usize = 0;
    #[type_const]
    const N2<const I: usize>: usize = 1;
    #[type_const]
    const N3: usize = 2;
    #[type_const]
    const NEW_CONST: usize = 3; // Added implementation for the new constant
}

fn main() {
    let _value = <S as Tr<0>>::NEW_CONST; // Local usage of the new associated constant
}