trait PrivateSquareRoot {}
pub trait Mul<Rhs = Self> {
    type Output: Mul;
}
pub trait IsGreaterOrEqual<Rhs> {
    type Output;
}
pub type Square<A: PrivateSquareRoot> = <A as Mul>::Output;
pub type GrEq<A, B> = <A as IsGreaterOrEqual<B>>::Output;
impl<A, B: PrivateSquareRoot> IsGreaterOrEqual<B> for A {
    type Output = ();
}
impl<U> PrivateSquareRoot for U
where
    U: Mul,
    Square<U>: Mul,
    GrEq<Self, Square<Square<U>>>: Sized,
    U: PrivateSquareRoot,
{}
fn main() {}
trait NewTrait {}
