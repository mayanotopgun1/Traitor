trait Tr1{
    type Output<T>: Tr2
    where T: Tr2;
}
struct ty1;
impl Tr1 for ty1 {
    type Output<T: Tr2> = T;
}

trait Tr2 {
    fn method() {}
}
struct ty2<T: Tr1>(T);



impl<T: Tr1> Tr2 for ty2<T> 
where <T as Tr1>::Output<Self>: Tr2 {}
/*
effectively:
impl Tr2 for ty2<ty1> where ty2<ty1>: Tr2 {}
*/

fn weird<A: Tr1>() {
   <ty2<A> as Tr2>::method();
}

fn main() {
    weird::<ty1>();
}
